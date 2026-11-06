"""The daily schedule email goes to anyone with a job tomorrow, whatever their role."""
from datetime import date, datetime, timedelta

from models import Inspection, db


def test_manager_with_a_job_gets_a_schedule_email(app, world, monkeypatch):
    import routes.email_notifications as en
    tomorrow = date.today() + timedelta(days=1)
    db.session.add(Inspection(property_id=world['property'].id, inspection_type='check_in', pdf_import=False,
                              inspector_id=world['manager'].id,
                              conduct_date=datetime.combine(tomorrow, datetime.min.time())))
    db.session.commit()

    sent_to = []
    monkeypatch.setattr('routes.email_service.send_clerk_daily_summary',
                        lambda user, tuples, **kw: (sent_to.append(user.name) or (True, None)))
    sent, errors = en._send_all_clerk_summaries()
    assert sent_to == ['Mia Manager'] and sent == 1 and not errors   # the clerk has no job, so no email
