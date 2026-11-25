"""Action tags: rules, learned memory, AI validation, and the two endpoints."""
import json
from types import SimpleNamespace

import pytest
from flask_jwt_extended import create_access_token

import routes.action_tags as at
from models import ActionTagDecision, SystemSetting, db

CONFIG = {
    'actions': [{'id': 'a1', 'name': 'Review'}, {'id': 'a2', 'name': 'Maintenance Required'},
                {'id': 'a4', 'name': 'Missing Item'}],
    'responsibilities': ['Tenant', 'Landlord/Agent', 'Investigate'],
}
ACTIONS, RESPS = CONFIG['actions'], CONFIG['responsibilities']


def row(line, action='a1', resp='Tenant', decision='accepted'):
    return ActionTagDecision(line=line, line_norm=at.normalise(line), final_action_id=action,
                             final_resp=resp, decision=decision, source='ai')


def test_rules_match_and_respect_catalogue():
    hit = at._rule_match('Not seen', ACTIONS, RESPS)
    assert (hit['actionId'], hit['responsibility'], hit['source']) == ('a4', 'Tenant', 'rule')
    assert at._rule_match('Unable to test - no power to property', ACTIONS, RESPS)['actionId'] == 'a2'
    assert at._rule_match('Heavy marks to door', ACTIONS, RESPS) is None
    # a rule whose action was deleted from the catalogue is skipped, not guessed
    assert at._rule_match('Not seen', [a for a in ACTIONS if a['id'] != 'a4'], RESPS) is None


def test_learned_needs_agreement_and_not_mostly_declined():
    norm = at.normalise('Chipping to lead edge')
    agree = [row('Chipping to lead edge'), row('chipping to lead edge.')]
    assert at._learned_match(norm, agree, ACTIONS, RESPS)['source'] == 'learned'
    assert at._learned_match(norm, agree[:1], ACTIONS, RESPS) is None                      # only one decision
    split = agree + [row('Chipping to lead edge', resp='Investigate'), row('Chipping to lead edge', resp='Investigate')]
    assert at._learned_match(norm, split, ACTIONS, RESPS) is None                          # 50% share < 80%
    declined = agree + [row('x', decision='declined'), row('x', decision='declined'), row('x', decision='declined')]
    assert at._learned_match(norm, declined, ACTIONS, RESPS) is None                       # mostly declined
    gone = [row('Chipping to lead edge', action='deleted'), row('Chipping to lead edge', action='deleted')]
    assert at._learned_match(norm, gone, ACTIONS, RESPS) is None                           # tag no longer exists


ITEMS = [{'id': '5', 'name': 'Walls', 'lines': ['Heavy marks', 'Small chip']}]


def test_ai_tags_validated_against_lines_and_catalogue():
    raw = [
        {'itemId': '5', 'line': 'Heavy marks', 'action': 'review', 'responsibility': 'tenant', 'confidence': 'high'},
        {'itemId': '5', 'line': 'Heavy marks', 'action': 'Review', 'responsibility': 'Tenant'},          # duplicate
        {'itemId': '5', 'line': 'Invented line', 'action': 'Review', 'responsibility': 'Tenant'},        # not a real line
        {'itemId': '9', 'line': 'Small chip', 'action': 'Review', 'responsibility': 'Tenant'},           # wrong item
        {'itemId': '5', 'line': 'Small chip', 'action': 'Bogus', 'responsibility': 'Tenant'},            # unknown action
        {'itemId': '5', 'line': 'Small chip', 'action': 'Review', 'responsibility': 'Nobody'},           # unknown resp
        'junk',
    ]
    out = at._validate_ai_tags(raw, ITEMS, ACTIONS, RESPS)
    assert list(out) == [('5', 'Heavy marks')]
    assert out[('5', 'Heavy marks')]['actionId'] == 'a1' and out[('5', 'Heavy marks')]['responsibility'] == 'Tenant'
    assert at._validate_ai_tags(None, ITEMS, ACTIONS, RESPS) == {}


def test_low_confidence_preserved():
    raw = [{'itemId': '5', 'line': 'Small chip', 'action': 'Review', 'responsibility': 'Investigate', 'confidence': 'low'}]
    assert at._validate_ai_tags(raw, ITEMS, ACTIONS, RESPS)[('5', 'Small chip')]['confidence'] == 'low'


@pytest.fixture()
def client(app, world, monkeypatch):
    app.register_blueprint(at.action_tags_bp, url_prefix='/api/action-tags')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'x')
    db.session.add(SystemSetting(key='actions_config', value=json.dumps(CONFIG)))
    db.session.commit()
    token = create_access_token(identity=str(world['clerk'].id))
    return SimpleNamespace(http=app.test_client(), h={'Authorization': f'Bearer {token}'})


def fake_anthropic(monkeypatch, reply):
    class Msgs:
        def create(self, **kw):
            self.kw = kw
            return SimpleNamespace(content=[SimpleNamespace(text=reply)], stop_reason='end_turn',
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    monkeypatch.setattr(at.anthropic, 'Anthropic', lambda **k: SimpleNamespace(messages=Msgs()))


def test_suggest_mixes_rule_learned_and_ai(client, monkeypatch):
    db.session.add_all([row('Light scuffing'), row('light scuffing')])
    db.session.commit()
    reply = json.dumps({'tags': [{'itemId': '5', 'line': 'Heavy marks', 'action': 'Review',
                                  'responsibility': 'Investigate', 'confidence': 'low', 'reason': 'Unclear'}]})[1:]
    fake_anthropic(monkeypatch, reply)
    r = client.http.post('/api/action-tags/suggest', headers=client.h, json={
        'roomName': 'Hall', 'items': [{'id': '5', 'name': 'Walls', 'lines': ['Not seen', 'Light scuffing', 'Heavy marks']}]})
    assert r.status_code == 200
    by_line = {s['line']: s for s in r.get_json()['suggestions']}
    assert by_line['Not seen']['source'] == 'rule'
    assert by_line['Light scuffing']['source'] == 'learned'
    assert by_line['Heavy marks']['source'] == 'ai' and by_line['Heavy marks']['confidence'] == 'low'


def test_suggest_with_everything_resolved_makes_no_ai_call(client, monkeypatch):
    monkeypatch.setattr(at.anthropic, 'Anthropic', lambda **k: pytest.fail('should not call the model'))
    r = client.http.post('/api/action-tags/suggest', headers=client.h,
                         json={'items': [{'id': '1', 'name': 'Oven', 'lines': ['Not seen']}]})
    assert r.status_code == 200 and len(r.get_json()['suggestions']) == 1


def test_additional_items_are_always_additional_item_tenant_without_ai(client, monkeypatch):
    cfg = {'actions': CONFIG['actions'] + [{'id': 'a9', 'name': 'Additional Item'}],
           'responsibilities': RESPS}
    SystemSetting.query.filter_by(key='actions_config').first().value = json.dumps(cfg)
    db.session.commit()
    monkeypatch.setattr(at.anthropic, 'Anthropic', lambda **k: pytest.fail('should not call the model'))
    r = client.http.post('/api/action-tags/suggest', headers=client.h, json={'items': [
        {'id': 'c1', 'name': 'Additional Item', 'kind': 'additional', 'lines': ['Chipped mirror', 'Not seen']}]})
    sugs = r.get_json()['suggestions']
    assert [(s['actionId'], s['responsibility'], s['source']) for s in sugs] == [('a9', 'Tenant', 'rule')] * 2
    # catalogue without that action -> falls through to the normal layers instead of guessing
    assert at._additional_item_match(ACTIONS, RESPS) is None


def test_suggest_empty_makes_no_ai_call(client, monkeypatch):
    monkeypatch.setattr(at.anthropic, 'Anthropic', lambda **k: pytest.fail('should not call the model'))
    r = client.http.post('/api/action-tags/suggest', headers=client.h, json={'items': [{'id': '1', 'lines': []}]})
    assert r.get_json() == {'suggestions': []}


def test_model_failure_is_a_502_when_nothing_else_resolved(client, monkeypatch):
    def boom(**k):
        raise RuntimeError('down')
    monkeypatch.setattr(at.anthropic, 'Anthropic', boom)
    r = client.http.post('/api/action-tags/suggest', headers=client.h,
                         json={'items': [{'id': '1', 'name': 'Wall', 'lines': ['Heavy marks']}]})
    assert r.status_code == 502


def test_decisions_are_recorded_and_accept_with_changes_becomes_edited(client):
    base = {'room': 'Hall', 'itemName': 'Walls', 'line': 'Heavy marks', 'suggestedActionId': 'a1', 'suggestedResp': 'Tenant'}
    r = client.http.post('/api/action-tags/decisions', headers=client.h, json={'inspectionId': None, 'decisions': [
        {**base, 'decision': 'accepted', 'finalActionId': 'a1', 'finalResp': 'Tenant'},
        {**base, 'decision': 'accepted', 'finalActionId': 'a2', 'finalResp': 'Tenant'},       # changed -> edited
        {**base, 'decision': 'declined', 'finalActionId': 'a1', 'finalResp': 'Tenant'},       # finals dropped
        {**base, 'decision': 'accepted', 'finalActionId': 'nope', 'finalResp': 'Tenant'},     # unknown tag -> skipped
        {**base, 'decision': 'maybe'},                                                         # bad decision -> skipped
        {'decision': 'accepted'},                                                              # no line -> skipped
    ]})
    assert r.get_json() == {'saved': 3}
    rows = ActionTagDecision.query.order_by(ActionTagDecision.id).all()
    assert [x.decision for x in rows] == ['accepted', 'edited', 'declined']
    assert rows[2].final_action_id is None and rows[0].line_norm == 'heavy marks'
