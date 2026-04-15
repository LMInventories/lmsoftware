"""
email_service.py — Core HTTP email sender (Resend API) and all email templates for InspectPro.

Templates:
  - send_inspection_notification()  → client notification emails
  - send_clerk_daily_summary()       → 6pm clerk work summary
  - send_report_complete()           → report complete with PDF attachment (reports@ address)

Env vars required on Railway:
  RESEND_API_KEY     re_xxxxxxxxxxxx  (from resend.com dashboard)
  SMTP_FROM          no-reply@lminventories.co.uk  (verified sender on Resend)
  SMTP_FROM_REPORTS  no-reply@lminventories.co.uk  (can be the same address)
  APP_BASE_URL       https://app.lminventories.co.uk   (used in email links)
"""

import os
import base64
from datetime import datetime
import resend

# ── Config ──────────────────────────────────────────────────────────────────
RESEND_API_KEY     = os.environ.get('RESEND_API_KEY', '')
SMTP_FROM          = os.environ.get('SMTP_FROM',          'no-reply@lminventories.co.uk')
SMTP_FROM_REPORTS  = os.environ.get('SMTP_FROM_REPORTS',  'no-reply@lminventories.co.uk')
SMTP_FROM_NAME     = os.environ.get('SMTP_FROM_NAME',     'L&M Inventories')
APP_BASE_URL       = os.environ.get('APP_BASE_URL', 'https://app.lminventories.co.uk/')

resend.api_key = RESEND_API_KEY


def _with_name(addr):
    """Wrap an email address with the sender display name: 'Name <addr>'."""
    if SMTP_FROM_NAME:
        return f'{SMTP_FROM_NAME} <{addr}>'
    return addr


# ── Low-level sender ─────────────────────────────────────────────────────────

def _send(from_addr, to_addrs, subject, html_body, attachments=None):
    """
    Send an email via Resend SDK (avoids Railway's outbound SMTP port block).
    to_addrs: list of strings or a comma-separated string.
    attachments: list of (filename, bytes) tuples.
    Returns (True, None) on success, (False, error_message) on failure.
    """
    if not RESEND_API_KEY:
        return False, 'RESEND_API_KEY not configured'

    if isinstance(to_addrs, str):
        to_addrs = [a.strip() for a in to_addrs.split(',') if a.strip()]
    if not to_addrs:
        return False, 'No recipients'

    params: resend.Emails.SendParams = {
        'from':    _with_name(from_addr),
        'to':      to_addrs,
        'subject': subject,
        'html':    html_body,
    }

    if attachments:
        params['attachments'] = [
            {
                'filename': fname,
                'content':  base64.b64encode(fdata).decode('utf-8'),
            }
            for fname, fdata in attachments
        ]

    try:
        print(f'[resend] sending to {to_addrs}')
        result = resend.Emails.send(params)
        print(f'[resend] sent OK — id: {result.get("id")}')
        return True, None
    except Exception as e:
        print(f'[resend] ERROR: {e}')
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
        + _info_row('Property', prop_addr + (' \u00b7 ' + prop_detail if prop_detail else ''))
        + _info_row('Type', _pill(insp_type, pill_c, pill_bg))
        + _info_row('Date', insp_date + (' at ' + insp_time if insp_time else ''))
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
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">2. &nbsp;Click your name icon in the bottom-left corner</td></tr>
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
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">2. &nbsp;Click your name icon in the bottom-left corner</td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">3. &nbsp;Select <strong>Change Password</strong></td></tr>
  <tr><td style="padding:4px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">4. &nbsp;Enter your current password, then choose a new one</td></tr>
</table>'''
        + _btn('Log In Now', login_url)
        + '''<p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#94a3b8;">If you did not expect this email, please contact us.</p>'''
    )

    subject = f'Welcome to InspectPro — {client.company or client.name}'
    return _send(SMTP_FROM, client.email, subject, _wrap(body, subject))


# ── 4. Password reset ────────────────────────────────────────────────────────

def send_password_reset(user, reset_url):
    """
    Send a password reset link to the user.
    reset_url: full URL including token, e.g. https://app.lminventories.co.uk/reset-password?token=abc123
    """
    if not getattr(user, 'email', ''):
        return False, 'No email address'

    body = (
        f'''<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:17px;font-weight:bold;color:#1e293b;">Reset your InspectPro password</p>'''
        f'''<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#475569;">Hi {user.name}, we received a request to reset your password. Click the button below to choose a new one. This link expires in 1 hour.</p>'''
        + _btn('Reset Password', reset_url)
        + '''<p style="margin:16px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#94a3b8;">If you didn\'t request a password reset, you can safely ignore this email — your password won\'t change.</p>'''
    )

    subject = 'InspectPro — Reset your password'
    return _send(SMTP_FROM, user.email, subject, _wrap(body, subject))


# ── 5. Typist assigned to inspection (processing stage) ──────────────────────

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

    prop_full = prop_addr + (' \u00b7 ' + prop_detail if prop_detail else '')
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
        override  = getattr(inspection, 'client_email_override', None)
        to_addrs  = override if override else (getattr(client, 'email', '') if client else '')

    if not to_addrs:
        return False, 'No recipient email'

    atts = []
    if pdf_bytes:
        atts.append((pdf_name, pdf_bytes))

    return _send(SMTP_FROM_REPORTS, to_addrs, subject, _wrap(body, subject),
                 attachments=atts if atts else None)


# ── 6. Confirmation email (key-holder reminder N days before inspection) ─────

DEFAULT_CONFIRMATION_TEMPLATE = """Dear {recipient_name},

This is a confirmation that a {inspection_type} inspection is scheduled at {property_address} on {date}{time_str}.

Key collection: {key_location}

{inspector_line}Please ensure access is available at the time of the inspection. If you need to rearrange or have any questions, please contact us as soon as possible.

Kind regards,
InspectPro
"""


def send_confirmation_email(
    recipient_email,
    recipient_name,
    inspection,
    property_obj,
    days_before,
    template=None,
):
    """
    Send a key-holder confirmation email N days before an inspection.
    recipient_email : resolved from key_location (tenant / client / etc.)
    recipient_name  : display name for greeting
    days_before     : used in subject line (Tomorrow / in 2 days / etc.)
    template        : plain-text body from settings; supports {placeholders}.
    """
    prop_addr   = getattr(property_obj, 'address', '') or '\u2014'
    insp_type   = _type_label(getattr(inspection, 'inspection_type', ''))
    insp_date   = _fmt_date(
        getattr(inspection, 'conduct_date', None) or
        getattr(inspection, 'scheduled_date', None)
    )
    insp_time   = _fmt_time(getattr(inspection, 'conduct_time_preference', None))
    time_str    = f' at {insp_time}' if insp_time else ''
    key_loc     = getattr(inspection, 'key_location', '') or 'as previously arranged'
    clerk       = inspection.inspector if getattr(inspection, 'inspector', None) else None
    clerk_name  = clerk.name if clerk else None
    inspector_line = f'Your inspector will be {clerk_name}. ' if clerk_name else ''

    if days_before == 1:
        day_label = 'Tomorrow'
    elif days_before == 7:
        day_label = 'in 1 week'
    else:
        day_label = f'in {days_before} days'

    subject = f'Inspection Confirmation \u2014 {prop_addr} ({day_label})'

    tmpl = (template or '').strip() or DEFAULT_CONFIRMATION_TEMPLATE

    plain_body = tmpl.format(
        recipient_name   = recipient_name,
        property_address = prop_addr,
        inspection_type  = insp_type,
        date             = insp_date,
        time             = insp_time or 'TBC',
        time_str         = time_str,
        key_location     = key_loc,
        inspector_name   = clerk_name or 'TBC',
        inspector_line   = inspector_line,
        days_before      = days_before,
        day_label        = day_label,
    )

    paragraphs_html = ''.join(
        f'<p style="margin:0 0 14px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;color:#475569;line-height:1.6;">{line}</p>'
        for line in plain_body.strip().split('\n')
        if line.strip()
    )

    body = (
        f'<p style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:17px;font-weight:bold;color:#1e293b;">'
        f'Inspection Confirmation \u2014 {day_label.capitalize()}</p>'
        + _info_table_open()
        + _info_row('Property', prop_addr)
        + _info_row('Type',     _pill(insp_type, '#1e40af', '#dbeafe'))
        + _info_row('Date',     insp_date + time_str)
        + _info_row('Keys',     key_loc, last=True)
        + _info_table_close()
        + f'<div style="margin-top:20px;">{paragraphs_html}</div>'
    )

    return _send(SMTP_FROM, recipient_email, subject, _wrap(body, subject))
