"""The read-only lookup tools: the new schedule / availability / unpaid-invoice tools and role scoping."""
from datetime import datetime, timedelta

import pytest

import routes.telegram_lookup as lookup
from routes.telegram_intent import _today_london


@pytest.fixture()
def jobs(world):
    from models import Client, Inspection, Property, User, db
    today = datetime.combine(_today_london(), datetime.min.time())
    other_clerk = User(name='Pat Clerk', email='pat@example.com', role='clerk', password_hash='x')
    other_client = Client(name='Beta Homes', email='b@example.com')
    db.session.add_all([other_clerk, other_client])
    db.session.flush()
    other_prop = Property(client_id=other_client.id, address='3 Other Road, Leeds LS1 1AA', bedrooms=1, bathrooms=1)
    db.session.add(other_prop)
    db.session.flush()
    rows = {
        'today_sam': Inspection(property_id=world['property'].id, inspection_type='check_in', status='assigned',
                                inspector_id=world['clerk'].id, conduct_date=today, conduct_time_preference='am',
                                reference_number='INS-1', pdf_import=False),
        'tomorrow_unassigned': Inspection(property_id=world['property'].id, inspection_type='midterm', status='created',
                                          conduct_date=today + timedelta(days=1), reference_number='INS-2', pdf_import=False),
        'done_unpaid': Inspection(property_id=world['property'].id, inspection_type='check_out', status='complete',
                                  conduct_date=today - timedelta(days=9), reference_number='INS-3',
                                  invoice_paid=False, pdf_import=False),
        'done_paid': Inspection(property_id=world['property'].id, inspection_type='check_in', status='complete',
                                conduct_date=today - timedelta(days=20), reference_number='INS-4',
                                invoice_paid=True, pdf_import=False),
        'other_unpaid': Inspection(property_id=other_prop.id, inspection_type='check_in', status='complete',
                                   conduct_date=today - timedelta(days=5), reference_number='INS-5',
                                   invoice_paid=False, pdf_import=False),
        'sams_other_client_job': Inspection(property_id=other_prop.id, inspection_type='check_in', status='assigned',
                                            inspector_id=other_clerk.id, conduct_date=today, reference_number='INS-6',
                                            pdf_import=False),
    }
    db.session.add_all(rows.values())
    db.session.commit()
    return {**world, 'other_clerk': other_clerk, 'other_client': other_client}


def _refs(result):
    return sorted(i['reference'] for i in result['inspections'])


def test_get_schedule_defaults_to_today(jobs):
    assert _refs(lookup.get_schedule(jobs['manager'])) == ['INS-1', 'INS-6']


def test_get_schedule_range_and_filters(jobs):
    tomorrow = (_today_london() + timedelta(days=1)).isoformat()
    result = lookup.get_schedule(jobs['manager'], date_from=_today_london().isoformat(), date_to=tomorrow)
    assert _refs(result) == ['INS-1', 'INS-2', 'INS-6']
    assert _refs(lookup.get_schedule(jobs['manager'], date_from=tomorrow, unassigned_only=True)) == ['INS-2']
    assert _refs(lookup.get_schedule(jobs['manager'], inspector_name='Sam')) == ['INS-1']


def test_get_availability(jobs):
    result = lookup.get_availability(jobs['manager'])
    assert result['free_clerks'] == []
    assert {c['name'] for c in result['busy_clerks']} == {'Sam Clerk', 'Pat Clerk'}
    far = lookup.get_availability(jobs['manager'], (_today_london() + timedelta(days=30)).isoformat())
    assert sorted(far['free_clerks']) == ['Pat Clerk', 'Sam Clerk'] and far['busy_clerks'] == []
    assert 'error' in lookup.get_availability(jobs['manager'], 'next tuesday')


def test_availability_is_managers_only(jobs):
    assert 'error' in lookup.get_availability(jobs['clerk'])


def test_unpaid_invoices(jobs):
    assert _refs(lookup.list_unpaid_invoices(jobs['manager'])) == ['INS-3', 'INS-5']       # oldest first
    assert _refs(lookup.list_unpaid_invoices(jobs['manager'], client_name='acme')) == ['INS-3']
    assert _refs(lookup.list_unpaid_invoices(jobs['manager'], client_id=jobs['other_client'].id)) == ['INS-5']
    assert 'error' in lookup.list_unpaid_invoices(jobs['manager'], client_name='nobody')


def test_unpaid_invoices_ambiguous_client(jobs):
    from models import Client, db
    db.session.add(Client(name='Acme Estates', email='x@example.com'))
    db.session.commit()
    result = lookup.list_unpaid_invoices(jobs['manager'], client_name='acme')
    assert 'error' in result and len(result['clients']) == 2


def test_clerk_only_sees_their_own_jobs(jobs):
    result = lookup.search_inspections(jobs['clerk'], include_paper_imports=True)
    assert _refs(result) == ['INS-1']
    assert lookup.get_inspection(jobs['clerk'], 6) == {'error': 'Inspection not found.'}


def test_run_tool_survives_bad_arguments(jobs):
    out = lookup._run_tool('get_schedule', {'nonsense': 1}, jobs['manager'])
    assert 'Bad arguments' in out
    assert 'Unknown tool' in lookup._run_tool('drop_tables', {}, jobs['manager'])
