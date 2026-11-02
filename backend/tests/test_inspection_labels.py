import pytest

from utils.inspection_labels import report_name, type_label, type_phrase


@pytest.mark.parametrize('raw,label,report,phrase', [
    ('heads_up',      'Heads Up Report',    'Heads Up Report',         'Heads Up Report'),
    ('damage_report', 'Damage Report',      'Damage Report',           'Damage Report'),
    ('midterm',       'Midterm Inspection', 'Midterm Inspection Report', 'Midterm'),
    ('check_in',      'Check In',           'Check In Report',         'Check In'),
    ('Check Out',     'Check Out',          'Check Out Report',        'Check Out'),
    (None,            'Inspection',         'Inspection Report',       'Inspection'),
    ('some_new_type', 'Some New Type',      'Some New Type Report',    'Some New Type'),
])
def test_labels(raw, label, report, phrase):
    assert type_label(raw) == label
    assert report_name(raw) == report
    assert type_phrase(raw) == phrase
    assert '_' not in type_label(raw)
