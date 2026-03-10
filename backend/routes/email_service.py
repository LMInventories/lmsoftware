"""
email_service.py — Core SMTP email sender and all email templates for InspectPro.

Templates:
  - send_inspection_notification()  → client notification emails
  - send_clerk_daily_summary()       → 6pm clerk work summary
  - send_report_complete()           → report complete with PDF attachment (reports@ address)

Env vars required on Render:
  SMTP_HOST       e.g. smtp.fasthosts.co.uk
  SMTP_PORT       587 (STARTTLS) or 465 (SSL)
  SMTP_USER       no-reply@lminventories.co.uk
  SMTP_PASSWORD   mailbox password
  SMTP_FROM       no-reply@lminventories.co.uk
  SMTP_FROM_REPORTS  reports@lminventories.co.uk  (for PDF emails)
  APP_BASE_URL    https://lmsoftware.vercel.app   (used in email links)
"""

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
SMTP_HOST          = os.environ.get('SMTP_HOST', 'smtp.fasthosts.co.uk')
SMTP_PORT          = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER          = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD      = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM          = os.environ.get('SMTP_FROM', 'no-reply@lminventories.co.uk')
SMTP_FROM_REPORTS  = os.environ.get('SMTP_FROM_REPORTS', 'reports@lminventories.co.uk')
APP_BASE_URL       = os.environ.get('APP_BASE_URL', 'https://lmsoftware.vercel.app')


# ── Low-level sender ─────────────────────────────────────────────────────────

def _send(from_addr, to_addrs, subject, html_body, attachments=None):
    """
    Send an email via SMTP.
    to_addrs: list of strings or a comma-separated string.
    attachments: list of (filename, bytes) tuples.
    Returns (True, None) on success, (False, error_message) on failure.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, 'SMTP credentials not configured'

    if isinstance(to_addrs, str):
        to_addrs = [a.strip() for a in to_addrs.split(',') if a.strip()]
    if not to_addrs:
        return False, 'No recipients'

    msg = MIMEMultipart('alternative') if not attachments else MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From']    = from_addr
    msg['To']      = ', '.join(to_addrs)

    html_part = MIMEText(html_body, 'html', 'utf-8')
    if attachments:
        # For mixed messages wrap HTML in a related part
        alt = MIMEMultipart('alternative')
        alt.attach(html_part)
        msg.attach(alt)
        for fname, fdata in attachments:
            part = MIMEApplication(fdata, Name=fname)
            part['Content-Disposition'] = f'attachment; filename="{fname}"'
            msg.attach(part)
    else:
        msg.attach(html_part)

    try:
        if SMTP_PORT == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(from_addr, to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(from_addr, to_addrs, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


# ── Shared HTML chrome ───────────────────────────────────────────────────────

def _wrap(content_html, title='InspectPro'):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
  body{{margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
  .wrap{{max-width:620px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
  .hd{{background:#1e3a8a;padding:24px 32px;}}
  .hd h1{{margin:0;color:#fff;font-size:20px;font-weight:700;letter-spacing:-.3px;}}
  .hd p{{margin:4px 0 0;color:#93c5fd;font-size:13px;}}
  .body{{padding:28px 32px;}}
  .body h2{{font-size:17px;font-weight:700;color:#1e293b;margin:0 0 16px;}}
  .body p{{font-size:14px;color:#475569;line-height:1.6;margin:0 0 12px;}}
  .pill{{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;}}
  .pill-blue{{background:#dbeafe;color:#1e40af;}}
  .pill-green{{background:#dcfce7;color:#166534;}}
  .pill-amber{{background:#fef3c7;color:#92400e;}}
  .pill-purple{{background:#ede9fe;color:#5b21b6;}}
  .info-box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;margin:16px 0;}}
  .info-row{{display:flex;gap:12px;padding:7px 0;border-bottom:1px solid #f1f5f9;font-size:14px;}}
  .info-row:last-child{{border-bottom:none;}}
  .info-label{{color:#94a3b8;font-weight:600;min-width:120px;flex-shrink:0;}}
  .info-value{{color:#1e293b;}}
  .btn{{display:inline-block;padding:11px 22px;background:#1e3a8a;color:#fff;text-decoration:none;border-radius:7px;font-size:14px;font-weight:600;margin-top:8px;}}
  .ft{{padding:20px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>LM Inventories</h1>
    <p>Property Inspection Management</p>
  </div>
  <div class="body">
    {content_html}
  </div>
  <div class="ft">
    This email was sent automatically by InspectPro · LM Inventories · lminventories.co.uk<br/>
    Please do not reply to this email.
  </div>
</div>
</body>
</html>"""


# ── Inspection type display name ─────────────────────────────────────────────

def _type_label(t):
    return {
        'inventory': 'Inventory', 'check_in': 'Check In', 'check_out': 'Check Out',
        'mid_term': 'Mid-Term Visit', 'interim': 'Interim Inspection',
        'snagging': 'Snagging', 'hhsrs': 'HHSRS',
    }.get((t or '').lower().replace(' ', '_'), t or 'Inspection')


def _fmt_date(d):
    if not d:
        return '—'
    try:
        if isinstance(d, str):
            d = datetime.fromisoformat(d)
        return d.strftime('%-d %B %Y')
    except Exception:
        return str(d)


def _fmt_time(t):
    """Parse conduct_time_preference into a display string."""
    if not t:
        return 'Anytime'
    t = str(t).strip().lower()
    if t in ('', 'anytime'):
        return 'Anytime'
    if t == 'am':
        return 'AM'
    if t == 'pm':
        return 'PM'
    if t.startswith('specific:'):
        # format: specific:HH_MM
        try:
            _, time_part = t.split(':', 1)
            hour, minute = time_part.split('_')
            return f"{int(hour):02d}:{minute}"
        except Exception:
            return t
    return t


def _sort_key(t):
    """Return a numeric sort key for ordering inspections by time preference.
    Order: specific AM → AM → specific PM → PM → Anytime
    """
    if not t:
        return (4, 0)
    t = str(t).strip().lower()
    if t.startswith('specific:'):
        try:
            _, time_part = t.split(':', 1)
            hour, minute = time_part.split('_')
            total_mins = int(hour) * 60 + int(minute)
            # AM specifics (before 12:00) → bucket 0, PM specifics → bucket 2
            return (0, total_mins) if int(hour) < 12 else (2, total_mins)
        except Exception:
            return (2, 0)
    if t == 'am':
        return (1, 0)
    if t == 'pm':
        return (3, 0)
    return (4, 0)  # anytime last


# ── 1. Client notification email ─────────────────────────────────────────────

def send_inspection_notification(event, inspection, client, property_obj):
    """
    Send a notification email to a client about an inspection event.
    event: 'created' | 'updated' | 'completed' | 'reminder'
    """
    prop_addr  = getattr(property_obj, 'address', '') or '—'
    beds       = getattr(property_obj, 'bedrooms', None)
    baths      = getattr(property_obj, 'bathrooms', None)
    beds_str   = f"{beds} bed" if beds else ''
    baths_str  = f"{baths} bath" if baths else ''
    prop_detail = ', '.join(filter(None, [beds_str, baths_str]))

    insp_type  = _type_label(getattr(inspection, 'inspection_type', ''))
    insp_date  = _fmt_date(getattr(inspection, 'conduct_date', None) or getattr(inspection, 'scheduled_date', None))
    insp_time  = _fmt_time(getattr(inspection, 'conduct_time_preference', None))
    clerk_name = inspection.inspector.name if getattr(inspection, 'inspector', None) else '—'

    event_config = {
        'created':   ('🆕 New Inspection Booked',   'pill-blue',   'New inspection scheduled'),
        'updated':   ('✏️ Inspection Updated',       'pill-amber',  'Inspection details have changed'),
        'completed': ('✅ Inspection Complete',       'pill-green',  'Inspection has been completed'),
        'reminder':  ('⏰ Inspection Reminder',       'pill-purple', 'Reminder: inspection tomorrow'),
    }
    subject, pill_class, headline = event_config.get(event, ('Inspection Update', 'pill-blue', 'Inspection update'))

    body = f"""
<h2>{headline}</h2>
<p>Dear {client.name},</p>
<p>{'Here is a summary of the upcoming inspection.' if event != 'completed' else 'The inspection has been completed. A full report will follow shortly.'}</p>
<div class="info-box">
  <div class="info-row"><span class="info-label">Property</span><span class="info-value">{prop_addr}{' · ' + prop_detail if prop_detail else ''}</span></div>
  <div class="info-row"><span class="info-label">Type</span><span class="info-value"><span class="pill {pill_class}">{insp_type}</span></span></div>
  <div class="info-row"><span class="info-label">Date</span><span class="info-value">{insp_date}{' at ' + insp_time if insp_time else ''}</span></div>
  <div class="info-row"><span class="info-label">Inspector</span><span class="info-value">{clerk_name}</span></div>
</div>
<p>If you have any questions, please contact us directly.</p>
"""

    # Determine recipient — use per-inspection override if set, otherwise client email
    override = getattr(inspection, 'client_email_override', None)
    recipients = override if override else getattr(client, 'email', '')

    return _send(SMTP_FROM, recipients, subject, _wrap(body, subject))


# ── 2. Clerk daily summary ───────────────────────────────────────────────────

def send_clerk_daily_summary(clerk, inspections_tomorrow):
    """
    Send a clerk their work summary for the following day.
    inspections_tomorrow: list of (inspection, property, client) tuples, sorted by time.
    """
    if not getattr(clerk, 'email', ''):
        return False, 'Clerk has no email address'

    date_str = '—'
    inspections_tomorrow = sorted(
        inspections_tomorrow,
        key=lambda x: _sort_key(getattr(x[0], 'conduct_time_preference', None))
    )
    if inspections_tomorrow:
        d = getattr(inspections_tomorrow[0][0], 'conduct_date', None) or \
            getattr(inspections_tomorrow[0][0], 'scheduled_date', None)
        date_str = _fmt_date(d)

    count = len(inspections_tomorrow)
    rows_html = ''

    for inspection, prop, client in inspections_tomorrow:
        insp_time  = _fmt_time(getattr(inspection, 'conduct_time_preference', None))
        prop_addr  = getattr(prop, 'address', '—') if prop else '—'
        beds       = getattr(prop, 'bedrooms', None)
        baths      = getattr(prop, 'bathrooms', None)
        prop_detail = ', '.join(filter(None, [f"{beds} bed" if beds else '', f"{baths} bath" if baths else '']))
        insp_type  = _type_label(getattr(inspection, 'inspection_type', ''))
        client_name = getattr(client, 'name', '—') if client else '—'
        client_addr = getattr(client, 'address', '') if client else ''
        key_loc    = getattr(inspection, 'key_location', '') or '—'
        key_ret    = getattr(inspection, 'key_return', '') or '—'
        notes      = getattr(inspection, 'internal_notes', '') or ''

        notes_row = f'<div class="info-row"><span class="info-label">Internal Notes</span><span class="info-value" style="color:#92400e;">{notes}</span></div>' if notes else ''
        client_addr_row = f'<div class="info-row"><span class="info-label">Client Address</span><span class="info-value">{client_addr}</span></div>' if client_addr else ''

        rows_html += f"""
<div class="info-box" style="margin-bottom:20px;">
  <div style="padding:10px 0 12px;border-bottom:1px solid #e2e8f0;margin-bottom:4px;">
    <div style="font-size:18px;font-weight:700;color:#1e293b;">{insp_time}</div>
    <span class="pill pill-blue" style="margin-top:6px;display:inline-block;">{insp_type}</span>
  </div>
  <div class="info-row"><span class="info-label">Property</span><span class="info-value">{prop_addr}</span></div>
  <div class="info-row"><span class="info-label">Bedrooms / Baths</span><span class="info-value">{prop_detail if prop_detail else '—'}</span></div>
  <div class="info-row"><span class="info-label">Client</span><span class="info-value">{client_name}</span></div>
  {client_addr_row}
  <div class="info-row"><span class="info-label">Key Collect</span><span class="info-value">{key_loc}</span></div>
  <div class="info-row"><span class="info-label">Key Return</span><span class="info-value">{key_ret}</span></div>
  {notes_row}
</div>"""

    no_jobs = '<p style="color:#94a3b8;font-style:italic;">No inspections scheduled for tomorrow.</p>' if not count else ''

    body = f"""
<h2>Your Work Summary for {date_str}</h2>
<p>Hi {clerk.name},</p>
<p>Here is your schedule for tomorrow — <strong>{count} inspection{'s' if count != 1 else ''}</strong>.</p>
{rows_html}
{no_jobs}
<p>If anything looks incorrect, please contact the office.</p>
"""

    subject = f'Your Schedule for {date_str} — {count} inspection{"s" if count != 1 else ""}'
    return _send(SMTP_FROM, clerk.email, subject, _wrap(body, subject))


# ── 3. Welcome emails (new user / new client) ───────────────────────────────

ROLE_LABELS = {
    'admin':   'Administrator',
    'manager': 'Manager',
    'clerk':   'Clerk / Inspector',
    'typist':  'Typist',
}

def send_welcome_user(user, plain_password):
    """
    Send a welcome email to a newly created user (any role).
    plain_password: the password as typed before hashing — only available at creation time.
    """
    if not getattr(user, 'email', ''):
        return False, 'No email address'

    role_label  = ROLE_LABELS.get(user.role, user.role.title())
    login_url   = f"{APP_BASE_URL}/login"

    role_notes = {
        'admin':   'As an administrator you have full access to all areas of InspectPro, including settings, templates, clients, and user management.',
        'manager': 'As a manager you can create and manage inspections, assign clerks and typists, and review completed reports.',
        'clerk':   'As a clerk you will be assigned inspections to carry out on-site. You can access your schedule and complete inspection reports via the InspectPro app.',
        'typist':  'As a typist you will be notified when inspection reports are ready for you to complete. Log in to the InspectPro portal to work on assigned reports.',
    }.get(user.role, '')

    body = f"""
<h2>Welcome to InspectPro, {user.name}!</h2>
<p>Your account has been set up. Your login details are below — please change your password the first time you log in.</p>

<div class="info-box">
  <div class="info-row"><span class="info-label">Name</span><span class="info-value">{user.name}</span></div>
  <div class="info-row"><span class="info-label">Email</span><span class="info-value">{user.email}</span></div>
  <div class="info-row"><span class="info-label">Password</span><span class="info-value" style="font-family:monospace;font-size:15px;letter-spacing:1px;">{plain_password}</span></div>
  <div class="info-row"><span class="info-label">Role</span><span class="info-value"><span class="pill pill-blue">{role_label}</span></span></div>
</div>

<p>{role_notes}</p>

<h3 style="font-size:15px;font-weight:700;color:#1e293b;margin:20px 0 10px;">How to change your password</h3>
<ol style="font-size:14px;color:#475569;line-height:1.8;padding-left:20px;margin:0 0 16px;">
  <li>Log in at <a href="{login_url}" style="color:#1e3a8a;">{login_url}</a></li>
  <li>Click your name icon in the top-right corner</li>
  <li>Select <strong>Change Password</strong></li>
  <li>Enter your current password, then choose a new one</li>
</ol>

<a href="{login_url}" class="btn">Log In Now</a>

<p style="margin-top:20px;font-size:13px;color:#94a3b8;">
  If you did not expect this email, please contact us immediately at no-reply@lminventories.co.uk.
</p>
"""

    subject = f'Welcome to InspectPro — Your {role_label} Account'
    return _send(SMTP_FROM, user.email, subject, _wrap(body, subject))


def send_welcome_client(client, plain_password):
    """
    Send a welcome email to a newly created client contact.
    plain_password: the password as typed before hashing.
    """
    if not getattr(client, 'email', ''):
        return False, 'No email address'

    login_url = f"{APP_BASE_URL}/login"

    body = f"""
<h2>Welcome to InspectPro, {client.name}!</h2>
<p>
  {client.company or 'Your account'} has been set up on InspectPro — LM Inventories' property inspection management platform.
  Your login details are below. Please change your password the first time you log in.
</p>

<div class="info-box">
  <div class="info-row"><span class="info-label">Name</span><span class="info-value">{client.name}</span></div>
  <div class="info-row"><span class="info-label">Email</span><span class="info-value">{client.email}</span></div>
  <div class="info-row"><span class="info-label">Password</span><span class="info-value" style="font-family:monospace;font-size:15px;letter-spacing:1px;">{plain_password}</span></div>
</div>

<p>
  Through InspectPro you will receive automated email notifications when inspections are scheduled, updated, or completed.
  Full reports will be sent to you on completion.
</p>

<h3 style="font-size:15px;font-weight:700;color:#1e293b;margin:20px 0 10px;">How to change your password</h3>
<ol style="font-size:14px;color:#475569;line-height:1.8;padding-left:20px;margin:0 0 16px;">
  <li>Log in at <a href="{login_url}" style="color:#1e3a8a;">{login_url}</a></li>
  <li>Click your name icon in the top-right corner</li>
  <li>Select <strong>Change Password</strong></li>
  <li>Enter your current password, then choose a new one</li>
</ol>

<a href="{login_url}" class="btn">Log In Now</a>

<p style="margin-top:20px;font-size:13px;color:#94a3b8;">
  If you did not expect this email, please contact us at no-reply@lminventories.co.uk.
</p>
"""

    subject = f'Welcome to InspectPro — {client.company or client.name}'
    return _send(SMTP_FROM, client.email, subject, _wrap(body, subject))


# ── 4. Typist assigned to inspection (processing stage) ──────────────────────

def send_typist_assignment(typist, inspection, property_obj, client):
    """
    Notify a typist that an inspection has entered Processing and is ready for them.
    """
    if not getattr(typist, 'email', ''):
        return False, 'Typist has no email address'

    prop_addr   = getattr(property_obj, 'address', '—') if property_obj else '—'
    beds        = getattr(property_obj, 'bedrooms', None)
    baths       = getattr(property_obj, 'bathrooms', None)
    prop_detail = ', '.join(filter(None, [f"{beds} bed" if beds else '', f"{baths} bath" if baths else '']))
    insp_type   = _type_label(getattr(inspection, 'inspection_type', ''))
    insp_date   = _fmt_date(getattr(inspection, 'conduct_date', None) or getattr(inspection, 'scheduled_date', None))
    clerk_name  = inspection.inspector.name if getattr(inspection, 'inspector', None) else '—'
    client_name = getattr(client, 'name', '—') if client else '—'
    login_url   = f"{APP_BASE_URL}/login"

    body = f"""
<h2>Report Ready for Typing</h2>
<p>Hi {typist.name},</p>
<p>
  An inspection has been completed and is now in the <strong>Processing</strong> stage — ready for you to type up.
  Audio recordings and photos are available in the app.
</p>

<div class="info-box">
  <div class="info-row"><span class="info-label">Property</span><span class="info-value">{prop_addr}{' · ' + prop_detail if prop_detail else ''}</span></div>
  <div class="info-row"><span class="info-label">Report Type</span><span class="info-value"><span class="pill pill-purple">{insp_type}</span></span></div>
  <div class="info-row"><span class="info-label">Date</span><span class="info-value">{insp_date}</span></div>
  <div class="info-row"><span class="info-label">Inspector</span><span class="info-value">{clerk_name}</span></div>
  <div class="info-row"><span class="info-label">Client</span><span class="info-value">{client_name}</span></div>
</div>

<p>Log in to InspectPro to open the report and begin typing. The inspection will be listed under your assigned reports.</p>

<a href="{login_url}" class="btn">Open InspectPro</a>

<p style="margin-top:20px;font-size:13px;color:#94a3b8;">
  Once you have completed the report, mark it as <strong>Review</strong> so it can be checked before sending.
</p>
"""

    subject = f'Report Ready: {insp_type} — {prop_addr}'
    return _send(SMTP_FROM, typist.email, subject, _wrap(body, subject))


# ── 3. Report complete (with PDF) ────────────────────────────────────────────

def send_report_complete(inspection, client, property_obj, pdf_bytes=None):
    """
    Send report-complete email from reports@ address, optionally with PDF attached.
    pdf_bytes: raw bytes of the PDF, or None to send without attachment.
    """
    prop_addr  = getattr(property_obj, 'address', '') or '—'
    insp_type  = _type_label(getattr(inspection, 'inspection_type', ''))
    insp_date  = _fmt_date(getattr(inspection, 'conduct_date', None) or getattr(inspection, 'scheduled_date', None))
    clerk_name = inspection.inspector.name if getattr(inspection, 'inspector', None) else '—'

    safe_addr = prop_addr.replace(',', '').replace(' ', '_')[:40]
    pdf_name  = f"InspectPro_{insp_type}_{safe_addr}_{insp_date.replace(' ', '_')}.pdf"

    body = f"""
<h2>Inspection Report: {insp_type}</h2>
<p>Dear {client.name},</p>
<p>Please find {'attached ' if pdf_bytes else ''}the completed inspection report for the property below.</p>
<div class="info-box">
  <div class="info-row"><span class="info-label">Property</span><span class="info-value">{prop_addr}</span></div>
  <div class="info-row"><span class="info-label">Report Type</span><span class="info-value"><span class="pill pill-green">{insp_type}</span></span></div>
  <div class="info-row"><span class="info-label">Date</span><span class="info-value">{insp_date}</span></div>
  <div class="info-row"><span class="info-label">Inspector</span><span class="info-value">{clerk_name}</span></div>
</div>
<p>Please review the report and contact us if you have any questions or concerns.</p>
"""

    subject     = f'Inspection Report: {insp_type} — {prop_addr}'
    override    = getattr(inspection, 'client_email_override', None)
    recipients  = override if override else getattr(client, 'email', '')
    attachments = [(pdf_name, pdf_bytes)] if pdf_bytes else None

    return _send(SMTP_FROM_REPORTS, recipients, subject, _wrap(body, subject), attachments=attachments)
