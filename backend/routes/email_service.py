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
    if not t:
        return ''
    return str(t)[:5]  # HH:MM


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
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <span style="font-size:15px;font-weight:700;color:#1e293b;">{insp_time or 'Time TBC'} — {prop_addr}</span>
    <span class="pill pill-blue">{insp_type}</span>
  </div>
  <div class="info-row"><span class="info-label">Property</span><span class="info-value">{prop_addr}{' · ' + prop_detail if prop_detail else ''}</span></div>
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
