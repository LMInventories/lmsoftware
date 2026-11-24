"""AI Proofread: suggestion validation, the two endpoints, and the glossary agent's use of decisions."""
import json
from types import SimpleNamespace

import pytest
from flask_jwt_extended import create_access_token

from models import ProofreadSuggestionLog, db
import routes.transcribe as tr
from learning.glossary_mining import build_candidates

ITEMS = [
    {'id': '55', 'name': 'Floor', 'description': 'Grey vinyl', 'condition': 'Worn to entrence\nLight scuffing',
     'subs': [{'id': 's1', 'description': 'Silver threshold', 'condition': 'Scratched 2 places'}]},
    {'id': '56', 'name': 'Walls', 'description': '', 'condition': ''},
]


def sug(**kw):
    base = {'itemId': '55', 'subId': None, 'field': 'condition', 'original': 'entrence',
            'suggested': 'entrance', 'kind': 'spelling', 'reason': 'Misspelt'}
    base.update(kw)
    return base


def test_valid_suggestion_is_kept_with_item_name():
    out = tr._validate_proofread_suggestions([sug()], ITEMS)
    assert len(out) == 1 and out[0]['itemName'] == 'Floor' and out[0]['original'] == 'entrence'


@pytest.mark.parametrize('bad', [
    sug(original='entrance not here'),                      # snippet not in the field text
    sug(original='entrence', suggested='entrence'),         # no change
    sug(field='description'),                               # snippet is in condition, not description
    sug(itemId='56'),                                       # empty item
    sug(field='bogus'),
    sug(field='sub_cond', subId=None),                      # sub field without a subId
    sug(field='sub_cond', subId='s1', original='2 places', suggested='3 places'),  # numbers must not change
])
def test_unsafe_suggestions_are_dropped(bad):
    assert tr._validate_proofread_suggestions([bad], ITEMS) == []


def test_sub_suggestion_and_unknown_kind_and_duplicates():
    s = sug(field='sub_cond', subId='s1', original='Scratched', suggested='Scratches', kind='nonsense')
    out = tr._validate_proofread_suggestions([s, s, 'junk'], ITEMS)
    assert len(out) == 1 and out[0]['subId'] == 's1' and out[0]['kind'] == 'wording'
    assert tr._validate_proofread_suggestions(None, ITEMS) == []


@pytest.fixture()
def client(app, world, monkeypatch):
    app.register_blueprint(tr.transcribe_bp, url_prefix='/api/transcribe')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'x')
    monkeypatch.setattr(tr, '_glossary_prompt', lambda: '')
    token = create_access_token(identity=str(world['clerk'].id))
    return SimpleNamespace(http=app.test_client(), h={'Authorization': f'Bearer {token}'}, world=world)


def fake_anthropic(monkeypatch, reply):
    class Msgs:
        def create(self, **kw):
            self.kw = kw
            return SimpleNamespace(content=[SimpleNamespace(text=reply)], stop_reason='end_turn',
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    monkeypatch.setattr(tr.anthropic, 'Anthropic', lambda **k: SimpleNamespace(messages=Msgs()))


def test_proofread_endpoint_filters_model_output(client, monkeypatch):
    reply = json.dumps({'suggestions': [sug(), sug(original='invented', suggested='x')]})[1:]  # prefill eats '{'
    fake_anthropic(monkeypatch, reply)
    r = client.http.post('/api/transcribe/proofread', headers=client.h,
                         json={'roomName': 'Kitchen', 'items': ITEMS})
    assert r.status_code == 200
    assert [s['original'] for s in r.get_json()['suggestions']] == ['entrence']


def test_proofread_empty_room_makes_no_ai_call(client, monkeypatch):
    monkeypatch.setattr(tr.anthropic, 'Anthropic', lambda **k: pytest.fail('should not call the model'))
    r = client.http.post('/api/transcribe/proofread', headers=client.h,
                         json={'roomName': 'Hall', 'items': [ITEMS[1]]})
    assert r.get_json() == {'suggestions': []}


def test_proofread_bad_model_json_is_a_clean_error(client, monkeypatch):
    fake_anthropic(monkeypatch, 'not json at all')
    r = client.http.post('/api/transcribe/proofread', headers=client.h, json={'items': ITEMS})
    assert r.status_code == 500 and 'try again' in r.get_json()['error']


def test_decisions_are_stored_and_junk_skipped(client):
    body = {'decisions': [
        {'room': 'Kitchen', 'itemName': 'Floor', 'field': 'condition', 'kind': 'spelling',
         'original': 'entrence', 'suggested': 'entrance', 'decision': 'accepted'},
        {'original': 'a', 'suggested': 'b', 'decision': 'maybe'},
        {'original': '', 'suggested': 'b', 'decision': 'dismissed'},
    ]}
    r = client.http.post('/api/transcribe/proofread/decisions', headers=client.h, json=body)
    assert r.get_json() == {'saved': 1}
    row = ProofreadSuggestionLog.query.one()
    assert row.decision == 'accepted' and row.user_id == client.world['clerk'].id


def row(i, insp, item, ai, final):
    return SimpleNamespace(id=i, inspection_id=insp, item_name=item, field='condition', inspector_id=1,
                           ai_value=ai, final_value=final, transcript_excerpt=None)


def test_glossary_counts_same_item_fix_once_across_sources():
    # Same fix on the same item arrives as a fill diff AND a proofread accept: counts once.
    rows = [row(1, 10, 'Floor', 'worn entrence', 'worn entrance'), row(2, 10, 'Floor', 'entrence', 'entrance'),
            row(3, 11, 'Floor', 'entrence', 'entrance')]
    assert build_candidates(rows, set()) == []          # 2 distinct inspection/item pairs < MIN_ROWS 3
    rows.append(row(4, 12, 'Door', 'entrence', 'entrance'))
    cands = build_candidates(rows, set())
    assert len(cands) == 1 and len(cands[0][1]['rows']) == 3


def test_glossary_skips_clusters_clerks_keep_dismissing():
    rows = [row(i, 10 + i, 'Floor', 'entrence', 'entrance') for i in range(3)]
    assert len(build_candidates(rows, set())) == 1
    assert build_candidates(rows, set(), {('entrence', 'entrance'): 3}) == []
    assert len(build_candidates(rows, set(), {('entrence', 'entrance'): 2})) == 1
