"""Walls: every surface is its own element, even when the AI merges them.

The merged examples are the shapes the room fill actually produced when "add sub item" was
followed by a paint colour."""
import pytest

from routes import transcribe as t

ITEMS = [{'id': '1', 'name': 'Walls'}, {'id': '2', 'name': 'Wall Units'}, {'id': '3', 'name': 'Contents'}]


def split(description='', condition='', **extra):
    out = t._split_wall_surfaces({'1': {'description': description, 'condition': condition, **extra}}, ITEMS)['1']
    parts = [(out.get('description'), out.get('condition'))]
    return parts + [(s['description'], s['condition']) for s in out.get('_subs', [])]


@pytest.mark.parametrize('description, condition, expected', [
    ('Beige tile', 'Good order\nPainted grey',
     [('Beige tile', 'Good order'), ('Painted grey', 'In good order')]),
    ('Painted white', 'Patchy rub marks at mid level\nPainted grey\nOccasional patchy marks scattered\n'
     '2 x filled in holes left of radiator',
     [('Painted white', 'Patchy rub marks at mid level'),
      ('Painted grey', 'Occasional patchy marks scattered\n2 x filled in holes left of radiator')]),
    ('Painted white', 'Hook high level right hand wall\nPainted light brown\nOccasional patchy paint at low level',
     [('Painted white', 'Hook high level right hand wall'),
      ('Painted light brown', 'Occasional patchy paint at low level')]),
    ('Beige tile', 'Grouting discoloured to bath area\n2 x rawl plug holes behind shower riser\nPainted beige\n'
     'Indent behind door',
     [('Beige tile', 'Grouting discoloured to bath area\n2 x rawl plug holes behind shower riser'),
      ('Painted beige', 'Indent behind door')]),
    ('Beige tiled', 'Crack to left side of tiled window ledge\nBeige painted\nHeavy rub marks either side of entry',
     [('Beige tiled', 'Crack to left side of tiled window ledge'),
      ('Beige painted', 'Heavy rub marks either side of entry')]),
    # Painted walls first, tiles merged into them - no trigger needed
    ('Painted white', 'Light scuffing to low level\nWhite tiled to bath area\nGrouting discoloured',
     [('Painted white', 'Light scuffing to low level'), ('White tiled to bath area', 'Grouting discoloured')]),
    ('Painted white\nPart beige tiled', 'In good order',
     [('Painted white', 'In good order'), ('Part beige tiled', 'In good order')]),
    ('Painted white and part beige tiled', 'In good order',
     [('Painted white', 'In good order'), ('Part beige tiled', 'In good order')]),
    # A defect belongs to the surface it was said about; none is invented for the other
    ('Painted white\nWhite tiled splashback', 'Light scuffing',
     [('Painted white', 'Light scuffing'), ('White tiled splashback', '')]),
    ('White tiled', 'Painted grey\nGood order',
     [('White tiled', 'In good order'), ('Painted grey', 'Good order')]),
    ('Painted white', 'Scuffs\nPart tiled\nPatterned wallpaper\nPeeling at seams',
     [('Painted white', 'Scuffs'), ('Part tiled', 'In good order'), ('Patterned wallpaper', 'Peeling at seams')]),
])
def test_second_surface_becomes_a_sub_item(description, condition, expected):
    assert split(description, condition) == expected


@pytest.mark.parametrize('line', [
    'Paint chip high level left of entry', 'Patchy scuff and paint touch up marks', 'Grouting discoloured',
    'Crack to left side of tiled window ledge', 'Tiled window ledge', 'Cracked tile above basin',
    'Odd painted over rawl plug holes', 'Painted around fittings', 'Painted over to facing wall',
    'Poorly painted at high level', 'Occasional patchy paint at low level', 'Heavy rub marks to painted frame',
    'In good order', '2 x that stick on hooks', 'Two tiles loose', 'White painted skirting',
    'Beige painted door frame', 'Marked to left hand wall',
])
def test_defects_and_locations_are_not_surfaces(line):
    assert split('Painted white', line) == [('Painted white', line)]


@pytest.mark.parametrize('description', ['White and grey tiled', 'Painted white\nWhite painted',
                                         'Painted white\nTextured'])
def test_a_single_surface_is_left_alone(description):
    fields = {'1': {'description': description, 'condition': 'In good order'}}
    assert t._split_wall_surfaces(fields, ITEMS) == fields


def test_retry_that_left_the_sub_item_on_the_main_item_too():
    got = split('White tiled', 'Grouting discoloured\nPainted brown\nLarge crack left of windows',
                _subs=[{'description': 'Brown painted', 'condition': 'Large crack left of windows'}])
    assert got == [('White tiled', 'Grouting discoloured'), ('Brown painted', 'Large crack left of windows')]


def test_two_surfaces_inside_one_sub_item_and_spoken_order():
    got = split('Painted white', 'Scuffs\nWhite tiled', _subs=[
        {'description': 'Painted grey', 'condition': 'Good order\nBlack tiled\nChipped'}])
    assert got == [('Painted white', 'Scuffs'), ('White tiled', 'In good order'),
                   ('Painted grey', 'Good order'), ('Black tiled', 'Chipped')]


@pytest.mark.parametrize('extra', [{'_condAction': 'append'}, {'_descAction': 'overwrite'}])
def test_amendments_are_left_as_dictated(extra):
    fields = {'1': {'description': 'Painted white', 'condition': 'White tiled', **extra}}
    assert t._split_wall_surfaces(fields, ITEMS) == fields


def test_only_the_walls_item_is_split():
    fields = {i: {'description': 'Painted white', 'condition': 'Painted grey'} for i in ('2', '3')}
    assert t._split_wall_surfaces(fields, ITEMS) == fields
    assert t._split_wall_surfaces({'1': {'_delete': True}}, ITEMS) == {'1': {'_delete': True}}
    assert t._is_walls_item('Walls & Tiles') and not t._is_walls_item('Wall Lights')


def test_split_survives_the_clean_up_and_needs_no_retry():
    transcript = 'Walls, beige tile, good order, add sub item, painted grey, good order.'
    calls = []

    def fill(*args, **kwargs):
        calls.append(kwargs)
        return {'1': {'description': 'Beige tile', 'condition': 'Good order\nPainted grey\nGood order'}}, None

    filled, _, ambiguous = t._fill_room_with_subitem_retry(fill, transcript, 'Kitchen', ITEMS[:1], [], 'test')
    assert len(calls) == 1 and ambiguous == []
    filled = t._strip_unspoken_fabrication(t._dedupe_cross_item_subs(
        t._dedupe_redirect_leaks(t._dedupe_filled(filled)), transcript, ITEMS[:1]), transcript)
    assert filled['1']['description'] == 'Beige tile' and filled['1']['condition'] == 'Good order'
    assert filled['1']['_subs'] == [{'description': 'Painted grey', 'condition': 'Good order'}]


def test_prompt_no_longer_says_a_new_colour_is_never_a_sub_item(monkeypatch):
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            self.messages = self

        def create(self, **kwargs):
            seen['prompt'] = kwargs['messages'][0]['content']
            block = type('Block', (), {'text': '}'})
            return type('Message', (), {'content': [block], 'stop_reason': 'end_turn'})

    monkeypatch.setattr(t.anthropic, 'Anthropic', Client)
    t._claude_fill_room('Walls. Painted white.', 'Kitchen', ITEMS)
    assert 'WALLS: EVERY SURFACE IS ITS OWN ELEMENT' in seen['prompt']
    assert 'new colour alone is not a trigger' not in seen['prompt']
