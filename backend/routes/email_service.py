"""
email_service.py — Core SMTP email sender and all email templates for InspectPro.

Templates:
  - send_inspection_notification()  → client notification emails
  - send_clerk_daily_summary()       → 6pm clerk work summary
  - send_report_complete()           → report complete with PDF attachment (reports@ address)

Env vars required on Render:
  SMTP_HOST       e.g. smtp.fasthosts.co.uk
  SMTP_PORT       587 (STARTTLS) or 465 (SSL)
  SMTP_USER       no-reply@inspectpro.co.uk  (or your sending address)
  SMTP_PASSWORD   mailbox password
  SMTP_FROM       no-reply@inspectpro.co.uk
  SMTP_FROM_REPORTS  reports@inspectpro.co.uk  (for PDF emails)
  APP_BASE_URL    https://app.lminventories.co.uk   (used in email links)
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
    """
    Outlook-safe HTML wrapper using table-based layout with inline styles.
    Outlook (desktop + mobile) ignores <style> blocks and most CSS classes.
    All layout and typography must be inline on the elements themselves.
    """
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
<meta name="x-apple-disable-message-reformatting"/>
<title>{title}</title>
<!--[if mso]>
<noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
<![endif]-->
<style>
  body, table, td {{ font-family: Arial, Helvetica, sans-serif !important; }}
  img {{ border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
  table {{ border-collapse: collapse !important; }}
  body {{ margin: 0 !important; padding: 0 !important; background-color: #f1f5f9; }}
  @media only screen and (max-width: 620px) {{
    .email-container {{ width: 100% !important; }}
    .fluid {{ max-width: 100% !important; height: auto !important; }}
    td.body-pad {{ padding: 20px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color:#f1f5f9;">
  <tr>
    <td style="padding:24px 16px;">
      <!-- Email container -->
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="620" class="email-container" style="margin:0 auto;background-color:#ffffff;border-radius:8px;overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background-color:#ffffff;padding:20px 32px;border-bottom:2px solid #1e3a8a;text-align:center;">
            <img src="https://app.lminventories.co.uk/ip-logo.png" alt="InspectPro" width="260" style="display:inline-block;height:auto;border:0;" />
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td class="body-pad" style="padding:28px 32px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;line-height:1.6;">
            {content_html}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 32px;background-color:#f8fafc;border-top:1px solid #e2e8f0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#94a3b8;">
            This email was sent automatically by InspectPro &middot; Property Reporting<br/>
            Please do not reply to this email.
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
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


# ── Outlook-safe inline HTML helpers ────────────────────────────────────────

def _pill(text, color='#1e40af', bg='#dbeafe'):
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:4px;'
            f'font-size:12px;font-weight:bold;color:{color};background-color:{bg};'
            f'font-family:Arial,Helvetica,sans-serif;">{text}</span>')

PILL_COLORS = {
    'blue':   ('#1e40af', '#dbeafe'),
    'green':  ('#166534', '#dcfce7'),
    'amber':  ('#92400e', '#fef3c7'),
    'purple': ('#5b21b6', '#ede9fe'),
}

def _info_table_open():
    return ('''<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" """
            """style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;margin:16px 0;">\n''')

def _info_table_close():
    return '</table>\n'

def _info_row(label, value, last=False):
    border = '' if last else 'border-bottom:1px solid #f1f5f9;'
    return (f'''<tr>
  <td style="{border}padding:8px 16px;font-family:Arial,Helvetica,sans-serif;font-size:13px;"""
          """color:#94a3b8;font-weight:bold;width:130px;vertical-align:top;">{label}</td>
  <td style="{border}padding:8px 16px;font-family:Arial,Helvetica,sans-serif;font-size:13px;"""
          """color:#1e293b;vertical-align:top;">{value}</td>
</tr>\n''')

def _section_heading(text):
    return (f'''<p style="margin:20px 0 6px;font-family:Arial,Helvetica,sans-serif;"""
            """font-size:15px;font-weight:bold;color:#1e293b;">{text}</p>\n''')

def _btn(text, url):
    return (f'''<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:16px 0;">
  <tr>
    <td style="background-color:#1e3a8a;border-radius:6px;padding:11px 22px;">
      <a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:14px;"""
            """font-weight:bold;color:#ffffff;text-decoration:none;">{text}</a>
    </td>
  </tr>
</table>\n''')


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

    pill_c, pill_bg = PILL_COLORS.get(pill_class.replace('pill-', ''), ('#1e40af', '#dbeafe'))
    intro = 'Here is a summary of the upcoming inspection.' if event != 'completed' else 'The inspection has been completed. A full report will follow shortly.'
    body = (
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">{headline}</p>'''
        f'''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Dear {client.name},</p>'''
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">{intro}</p>'''
        + _info_table_open()
        + _info_row('Property', f'{prop_addr}{' · ' + prop_detail if prop_detail else ""}')
        + _info_row('Type', _pill(insp_type, pill_c, pill_bg))
        + _info_row('Date', f'{insp_date}{' at ' + insp_time if insp_time else ""}')
        + _info_row('Inspector', clerk_name, last=True)
        + _info_table_close()
        + '''<p style="margin:12px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">If you have any questions, please contact us directly.</p>'''
    )

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

        # Build row list so we can mark the last one correctly
        card_rows = [
            ('Property',        prop_addr),
            ('Bedrooms / Baths', prop_detail if prop_detail else '—'),
            ('Client',          client_name),
        ]
        if client_addr:
            card_rows.append(('Client Address', client_addr))
        card_rows.append(('Key Collect', key_loc))
        card_rows.append(('Key Return',  key_ret))
        if notes:
            card_rows.append(('Internal Notes', f'<span style="color:#92400e;font-weight:bold;">{notes}</span>'))

        rows_html += (
            '''<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;margin:0 0 20px;">\n'''
            + f'''<tr><td colspan="2" style="padding:12px 16px 10px;border-bottom:1px solid #e2e8f0;">'''
            + f'''<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:20px;font-weight:bold;color:#1e293b;">{insp_time}</p>'''
            + f'''<p style="margin:4px 0 0;">{_pill(insp_type)}</p>'''
            + '</td></tr>\n'
            + ''.join(_info_row(lbl, val, last=(i == len(card_rows) - 1)) for i, (lbl, val) in enumerate(card_rows))
            + '</table>\n'
        )

    no_jobs = '<p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#94a3b8;font-style:italic;">No inspections scheduled for tomorrow.</p>' if not count else ''

    body = (
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">Your Work Summary for {date_str}</p>'''
        f'''<p style="margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Hi {clerk.name},</p>'''
        f'''<p style="margin:0 0 20px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Here is your schedule for tomorrow &mdash; <strong>{count} inspection{'s' if count != 1 else ''}</strong>.</p>'''
        + rows_html
        + no_jobs
        + '''<p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">If anything looks incorrect, please contact the office.</p>'''
    )

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

    body = (
        f'''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">Welcome to InspectPro, {user.name}!</p>'''
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Your account has been set up. Your login details are below &mdash; please change your password the first time you log in.</p>'''
        + _info_table_open()
        + _info_row('Name',     user.name)
        + _info_row('Email',    user.email)
        + _info_row('Password', f'<span style="font-family:Courier New,Courier,monospace;font-size:14px;letter-spacing:1px;color:#1e293b;">{plain_password}</span>')
        + _info_row('Role',     _pill(role_label), last=True)
        + _info_table_close()
        + f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">{role_notes}</p>'''
        + '''<p style="margin:0 0 8px;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#1e293b;">How to change your password</p>'''
        + f'''<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:0 0 16px;">
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">1. &nbsp;Log in at <a href="{login_url}" style="color:#1e3a8a;">{login_url}</a></td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">2. &nbsp;Click your name icon in the top-right corner</td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">3. &nbsp;Select <strong>Change Password</strong></td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">4. &nbsp;Enter your current password, then choose a new one</td></tr>
</table>'''
        + _btn('Log In Now', login_url)
        + '''<p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#94a3b8;">If you did not expect this email, please contact us immediately.</p>'''
    )

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

    account_name = client.company or 'Your account'
    body = (
        f'''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">Welcome to InspectPro, {client.name}!</p>'''
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">{account_name} has been set up on InspectPro &mdash; your property inspection management platform. Your login details are below. Please change your password the first time you log in.</p>'''
        + _info_table_open()
        + _info_row('Name',     client.name)
        + _info_row('Email',    client.email)
        + _info_row('Password', f'<span style="font-family:Courier New,Courier,monospace;font-size:14px;letter-spacing:1px;color:#1e293b;">{plain_password}</span>', last=True)
        + _info_table_close()
        + '''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Through InspectPro you will receive automated email notifications when inspections are scheduled, updated, or completed. Full reports will be sent to you on completion.</p>'''
        + '''<p style="margin:0 0 8px;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#1e293b;">How to change your password</p>'''
        + f'''<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="margin:0 0 16px;">
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">1. &nbsp;Log in at <a href="{login_url}" style="color:#1e3a8a;">{login_url}</a></td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">2. &nbsp;Click your name icon in the top-right corner</td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">3. &nbsp;Select <strong>Change Password</strong></td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">4. &nbsp;Enter your current password, then choose a new one</td></tr>
</table>'''
        + _btn('Log In Now', login_url)
        + '''<p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#94a3b8;">If you did not expect this email, please contact us.</p>'''
    )

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

    prop_full = f'{prop_addr}{' · ' + prop_detail if prop_detail else ""}' 
    body = (
        f'''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">Report Ready for Typing</p>'''
        f'''<p style="margin:0 0 6px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Hi {typist.name},</p>'''
        '''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">An inspection has been completed and is now in the <strong>Processing</strong> stage &mdash; ready for you to type up. Audio recordings and photos are available in the app.</p>'''
        + _info_table_open()
        + _info_row('Property',    prop_full)
        + _info_row('Report Type', _pill(insp_type, *PILL_COLORS['purple']))
        + _info_row('Date',        insp_date)
        + _info_row('Inspector',   clerk_name)
        + _info_row('Client',      client_name, last=True)
        + _info_table_close()
        + '''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Log in to InspectPro to open the report and begin typing. The inspection will be listed under your assigned reports.</p>'''
        + _btn('Open InspectPro', login_url)
        + '''<p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#94a3b8;">Once you have completed the report, mark it as <strong>Review</strong> so it can be checked before sending.</p>'''
    )

    subject = f'Report Ready: {insp_type} — {prop_addr}'
    return _send(SMTP_FROM, typist.email, subject, _wrap(body, subject))


# ── 3. Report complete (with PDF) ────────────────────────────────────────────

def send_report_complete(inspection, client, property_obj, pdf_bytes=None, recipients=None):
    """
    Send report-complete email from reports@ address, optionally with PDF attached.

    pdf_bytes:  raw bytes of the PDF, or None to send without attachment.
    recipients: explicit deduplicated list of email strings built by
                pdf_generator._get_report_recipients() — covers client email
                (or override) plus tenant, without duplication. Falls back to
                the old client_email_override / client.email logic if omitted.
    """
    prop_addr  = getattr(property_obj, 'address', '') or '—'
    insp_type  = _type_label(getattr(inspection, 'inspection_type', ''))
    insp_date  = _fmt_date(getattr(inspection, 'conduct_date', None) or getattr(inspection, 'scheduled_date', None))
    clerk_name = inspection.inspector.name if getattr(inspection, 'inspector', None) else '—'

    safe_addr = prop_addr.replace(',', '').replace(' ', '_')[:40]
    pdf_name  = f"InspectPro_{insp_type}_{safe_addr}_{insp_date.replace(' ', '_')}.pdf"

    attached_text = 'attached ' if pdf_bytes else ''
    body = (
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">Inspection Report: {insp_type}</p>'''
        f'''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Dear {client.name},</p>'''
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Please find {attached_text}the completed inspection report for the property below.</p>'''
        + _info_table_open()
        + _info_row('Property',    prop_addr)
        + _info_row('Report Type', _pill(insp_type, *PILL_COLORS['green']))
        + _info_row('Date',        insp_date)
        + _info_row('Inspector',   clerk_name, last=True)
        + _info_table_close()
        + '''<p style="margin:12px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Please review the report and contact us if you have any questions or concerns.</p>'''
    )

    subject = f'Inspection Report: {insp_type} — {prop_addr}'

    # Use explicit deduplicated list if provided; otherwise fall back to old logic
    if recipients:
        to_addrs = recipients
    else:
        override = getattr(inspection, 'client_email_override', None)
        to_addrs = override if override else getattr(client, 'email', '')

    attachments = [(pdf_name, pdf_bytes)] if pdf_bytes else None

    return _send(SMTP_FROM_REPORTS, to_addrs, subject, _wrap(body, subject), attachments=attachments)
