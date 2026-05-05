"""
signatures.py — Inspection signing routes.

API (auth required):
  GET  /api/inspections/<id>/signatures          → list all signatures for an inspection
  POST /api/inspections/<id>/signatures          → save an in-person signature (clerk/tenant/landlord_agent)
  POST /api/inspections/<id>/signing-links       → generate tokens + send signing-link emails

Public (no auth):
  GET  /sign/<token>   → serve the signing page HTML
  POST /sign/<token>   → accept a remote signature submission
"""

import os
import secrets
import base64
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, InspectionSignature, Inspection

signatures_bp = Blueprint('signatures', __name__)

APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://app.lminventories.co.uk').rstrip('/')
TOKEN_EXPIRY_DAYS = 30


# ── Helper ────────────────────────────────────────────────────────────────────

def _inspection_or_404(inspection_id):
    insp = Inspection.query.get(inspection_id)
    if not insp:
        return None
    return insp


# ── Auth-required endpoints ───────────────────────────────────────────────────

@signatures_bp.route('/inspections/<int:inspection_id>/signatures', methods=['GET'])
@jwt_required()
def get_signatures(inspection_id):
    """Return all signature records for an inspection (no image data — just status)."""
    sigs = InspectionSignature.query.filter_by(inspection_id=inspection_id).all()
    return jsonify([s.to_dict() for s in sigs])


@signatures_bp.route('/inspections/<int:inspection_id>/signatures', methods=['POST'])
@jwt_required()
def save_signature(inspection_id):
    """
    Save an in-person signature captured on the mobile app.
    Body: { role, signer_name, signature_data (base64 PNG) }
    If a record for that role already exists it is replaced.
    """
    insp = _inspection_or_404(inspection_id)
    if not insp:
        return jsonify({'error': 'Inspection not found'}), 404

    data = request.get_json(silent=True) or {}
    role = data.get('role')
    if role not in ('clerk', 'tenant', 'landlord_agent'):
        return jsonify({'error': 'Invalid role'}), 400

    sig_data = data.get('signature_data', '')
    if not sig_data:
        return jsonify({'error': 'signature_data is required'}), 400

    # Replace any existing in-person record for this role
    existing = InspectionSignature.query.filter_by(
        inspection_id=inspection_id, role=role, method='in_person'
    ).first()
    if existing:
        db.session.delete(existing)

    sig = InspectionSignature(
        inspection_id  = inspection_id,
        role           = role,
        signer_name    = data.get('signer_name', ''),
        signature_data = sig_data,
        signed_at      = datetime.utcnow(),
        method         = 'in_person',
    )
    db.session.add(sig)
    db.session.commit()
    return jsonify(sig.to_dict()), 201


@signatures_bp.route('/inspections/<int:inspection_id>/signing-links', methods=['POST'])
@jwt_required()
def send_signing_links(inspection_id):
    """
    Generate remote-signing tokens for tenant and/or landlord_agent and email them.
    Body: { roles: ['tenant', 'landlord_agent'] }   — defaults to ['tenant']
    Re-sending revokes the old token and issues a new one.
    """
    from routes.email_service import send_signing_link_email

    insp = _inspection_or_404(inspection_id)
    if not insp:
        return jsonify({'error': 'Inspection not found'}), 404

    data = request.get_json(silent=True) or {}
    roles = data.get('roles', ['tenant'])
    results = {}

    for role in roles:
        if role not in ('tenant', 'landlord_agent'):
            continue

        # Determine recipient email
        if role == 'tenant':
            email = insp.tenant_email
            name  = insp.tenant_name or 'Tenant'
        else:
            email = insp.landlord_email
            name  = 'Landlord / Agent'

        if not email:
            results[role] = {'sent': False, 'error': 'No email address on record'}
            continue

        # Revoke any existing pending token for this role
        old = InspectionSignature.query.filter_by(
            inspection_id=inspection_id, role=role, method='remote', signed_at=None
        ).first()
        if old:
            db.session.delete(old)

        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS)

        sig = InspectionSignature(
            inspection_id    = inspection_id,
            role             = role,
            signer_name      = name,
            method           = 'remote',
            token            = token,
            token_expires_at = expires,
        )
        db.session.add(sig)
        db.session.flush()   # get the ID without committing

        signing_url = f'{APP_BASE_URL}/sign/{token}'
        ok, err = send_signing_link_email(insp, role, name, email, signing_url)
        results[role] = {'sent': ok, 'error': err}

    db.session.commit()
    return jsonify(results)


# ── Public signing endpoints (no JWT) ────────────────────────────────────────

@signatures_bp.route('/sign/<token>', methods=['GET'])
def signing_page(token):
    """Serve the signing page for a remote-signing link."""
    sig = InspectionSignature.query.filter_by(token=token, method='remote').first()

    if not sig:
        return _signing_error('This signing link is invalid or has already been used.')

    if sig.token_expires_at and datetime.utcnow() > sig.token_expires_at:
        return _signing_error('This signing link has expired. Please contact your agent to request a new one.')

    if sig.signed_at:
        return _signing_already_done(sig)

    insp = sig.inspection
    role_label = {'clerk': 'Inspector / Clerk', 'tenant': 'Tenant', 'landlord_agent': 'Landlord / Agent'}.get(sig.role, sig.role.title())
    conduct_date = ''
    if insp.conduct_date:
        try:
            conduct_date = insp.conduct_date.strftime('%-d %B %Y')
        except Exception:
            conduct_date = str(insp.conduct_date)

    type_label = {
        'inventory': 'Inventory', 'check_in': 'Check In', 'check_out': 'Check Out',
        'mid_term': 'Mid-Term Visit', 'interim': 'Interim Inspection',
        'snagging': 'Snagging', 'hhsrs': 'HHSRS',
    }.get((insp.inspection_type or '').lower().replace(' ', '_'), insp.inspection_type or 'Inspection')

    address = insp.property.address if insp.property else '—'

    html = _signing_page_html(
        token=token,
        role_label=role_label,
        signer_name=sig.signer_name or '',
        address=address,
        type_label=type_label,
        conduct_date=conduct_date,
    )
    return make_response(html, 200, {'Content-Type': 'text/html; charset=utf-8'})


@signatures_bp.route('/sign/<token>', methods=['POST'])
def submit_signature(token):
    """Accept a remote signature submission."""
    sig = InspectionSignature.query.filter_by(token=token, method='remote').first()

    if not sig:
        return jsonify({'error': 'Invalid token'}), 404
    if sig.token_expires_at and datetime.utcnow() > sig.token_expires_at:
        return jsonify({'error': 'Link expired'}), 410
    if sig.signed_at:
        return jsonify({'error': 'Already signed'}), 409

    data = request.get_json(silent=True) or {}
    sig_data = data.get('signature_data', '')
    if not sig_data:
        return jsonify({'error': 'signature_data required'}), 400

    sig.signature_data = sig_data
    sig.signer_name    = data.get('signer_name', sig.signer_name or '')
    sig.signed_at      = datetime.utcnow()
    sig.ip_address     = request.remote_addr
    # Keep token in DB so the confirmation page still works, but null it so it
    # can't be re-used for another submission (unique constraint on non-null tokens
    # only applies while the value is present — we clear it after signing).
    sig.token = None
    db.session.commit()

    return jsonify({'ok': True, 'signed_at': sig.signed_at.isoformat()})


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _signing_error(message):
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signing Link — InspectPro</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f1f5f9; min-height: 100vh; display: flex;
          align-items: center; justify-content: center; padding: 24px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 40px 32px;
           max-width: 480px; width: 100%; text-align: center;
           box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
  .icon {{ font-size: 48px; margin-bottom: 16px; }}
  h2 {{ font-size: 20px; color: #1e293b; margin-bottom: 12px; }}
  p {{ font-size: 15px; color: #64748b; line-height: 1.6; }}
</style></head><body>
<div class="card">
  <div class="icon">⚠️</div>
  <h2>Link Unavailable</h2>
  <p>{message}</p>
</div></body></html>"""
    return make_response(html, 410, {'Content-Type': 'text/html; charset=utf-8'})


def _signing_already_done(sig):
    signed_str = sig.signed_at.strftime('%-d %B %Y at %H:%M') if sig.signed_at else '—'
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Already Signed — InspectPro</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f1f5f9; min-height: 100vh; display: flex;
          align-items: center; justify-content: center; padding: 24px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 40px 32px;
           max-width: 480px; width: 100%; text-align: center;
           box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
  .icon {{ font-size: 48px; margin-bottom: 16px; }}
  h2 {{ font-size: 20px; color: #1e293b; margin-bottom: 12px; }}
  p {{ font-size: 15px; color: #64748b; line-height: 1.6; }}
  .pill {{ display:inline-block; background:#dcfce7; color:#16a34a;
           font-weight:700; border-radius:20px; padding:6px 18px;
           font-size:14px; margin-top:16px; }}
</style></head><body>
<div class="card">
  <div class="icon">✅</div>
  <h2>Document Already Signed</h2>
  <p>This document was signed on <strong>{signed_str}</strong>.</p>
  <div class="pill">Signature recorded</div>
</div></body></html>"""
    return make_response(html, 200, {'Content-Type': 'text/html; charset=utf-8'})


def _signing_page_html(token, role_label, signer_name, address, type_label, conduct_date):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign Document — InspectPro</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f1f5f9; min-height: 100vh; padding: 24px 16px; }}
  .wrap {{ max-width: 560px; margin: 0 auto; }}
  .logo {{ text-align: center; margin-bottom: 20px; }}
  .logo img {{ height: 40px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 28px 24px;
           box-shadow: 0 4px 24px rgba(0,0,0,0.08); margin-bottom: 16px; }}
  .badge {{ display: inline-block; background: #eff6ff; color: #1e40af;
            font-size: 12px; font-weight: 700; border-radius: 20px;
            padding: 4px 12px; text-transform: uppercase; letter-spacing: 0.5px;
            margin-bottom: 14px; }}
  h1 {{ font-size: 20px; font-weight: 700; color: #1e293b; margin-bottom: 6px; }}
  .address {{ font-size: 15px; color: #475569; margin-bottom: 4px; }}
  .meta {{ font-size: 13px; color: #94a3b8; }}
  .divider {{ border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }}
  .declaration {{ font-size: 14px; color: #475569; line-height: 1.65;
                  background: #f8fafc; border-radius: 8px; padding: 16px; }}
  label {{ display: block; font-size: 13px; font-weight: 600; color: #374151;
           margin-bottom: 6px; margin-top: 16px; }}
  input[type=text] {{ width: 100%; padding: 10px 14px; border: 1.5px solid #d1d5db;
                      border-radius: 8px; font-size: 15px; color: #1e293b;
                      outline: none; transition: border-color .15s; }}
  input[type=text]:focus {{ border-color: #1e3a8a; }}
  .canvas-wrap {{ position: relative; margin-top: 8px; }}
  canvas {{ display: block; width: 100%; height: 180px; border: 1.5px solid #d1d5db;
            border-radius: 8px; background: #fff; touch-action: none; cursor: crosshair; }}
  canvas.has-sig {{ border-color: #1e3a8a; }}
  .canvas-hint {{ font-size: 12px; color: #94a3b8; text-align: center; margin-top: 6px; }}
  .clear-btn {{ position: absolute; top: 8px; right: 8px;
                background: #fff; border: 1px solid #d1d5db; border-radius: 6px;
                padding: 4px 10px; font-size: 12px; color: #64748b; cursor: pointer; }}
  .submit-btn {{ display: block; width: 100%; margin-top: 24px;
                 background: #1e3a8a; color: #fff; border: none;
                 border-radius: 10px; padding: 15px; font-size: 16px;
                 font-weight: 700; cursor: pointer; transition: background .15s; }}
  .submit-btn:hover {{ background: #1e40af; }}
  .submit-btn:disabled {{ background: #94a3b8; cursor: not-allowed; }}
  .error {{ color: #dc2626; font-size: 13px; margin-top: 10px; display: none; }}
  .success-card {{ display: none; text-align: center; padding: 40px 24px; }}
  .success-icon {{ font-size: 56px; margin-bottom: 16px; }}
  .success-card h2 {{ font-size: 22px; color: #1e293b; margin-bottom: 10px; }}
  .success-card p {{ font-size: 15px; color: #64748b; line-height: 1.6; }}
  .pill {{ display:inline-block; background:#dcfce7; color:#16a34a;
           font-weight:700; border-radius:20px; padding:6px 18px;
           font-size:14px; margin-top:16px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo">
    <img src="{APP_BASE_URL}/ip-logo.png" alt="InspectPro" onerror="this.style.display='none'" />
  </div>

  <!-- Signing form -->
  <div id="formCard" class="card">
    <div class="badge">Document Signing</div>
    <h1>{type_label} Report</h1>
    <p class="address">{address}</p>
    <p class="meta">{conduct_date}</p>

    <hr class="divider">

    <div class="declaration">
      I, the undersigned, confirm that I have had the opportunity to review the contents of this
      {type_label.lower()} report and agree that it accurately represents the condition of the
      property at the time of inspection. I understand that this document may be used as evidence
      in any future deposit dispute or legal proceedings.
    </div>

    <label>Your full name <span style="color:#dc2626">*</span></label>
    <input type="text" id="signerName" placeholder="e.g. Jane Smith" value="{signer_name}" />

    <label>Signature <span style="color:#dc2626">*</span></label>
    <div class="canvas-wrap">
      <canvas id="sigCanvas"></canvas>
      <button class="clear-btn" onclick="clearCanvas()">Clear</button>
    </div>
    <p class="canvas-hint">Draw your signature using your finger or mouse</p>

    <p class="error" id="errMsg"></p>

    <button class="submit-btn" id="submitBtn" onclick="submitSignature()">
      Sign Document
    </button>
  </div>

  <!-- Success state -->
  <div id="successCard" class="card success-card">
    <div class="success-icon">✅</div>
    <h2>Document Signed</h2>
    <p>Your signature has been recorded successfully.<br>You can now close this page.</p>
    <div class="pill">Signature confirmed</div>
  </div>
</div>

<script>
const canvas = document.getElementById('sigCanvas');
const ctx = canvas.getContext('2d');
let drawing = false;
let hasSig = false;

function resizeCanvas() {{
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width  = rect.width  * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
}}

function getPos(e) {{
  const r = canvas.getBoundingClientRect();
  const src = e.touches ? e.touches[0] : e;
  return {{ x: src.clientX - r.left, y: src.clientY - r.top }};
}}

canvas.addEventListener('mousedown',  e => {{ drawing = true; const p = getPos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }});
canvas.addEventListener('mousemove',  e => {{ if (!drawing) return; const p = getPos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); hasSig = true; canvas.classList.add('has-sig'); }});
canvas.addEventListener('mouseup',    () => drawing = false);
canvas.addEventListener('mouseleave', () => drawing = false);
canvas.addEventListener('touchstart', e => {{ e.preventDefault(); drawing = true; const p = getPos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }}, {{passive:false}});
canvas.addEventListener('touchmove',  e => {{ e.preventDefault(); if (!drawing) return; const p = getPos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); hasSig = true; canvas.classList.add('has-sig'); }}, {{passive:false}});
canvas.addEventListener('touchend',   () => drawing = false);

function clearCanvas() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  hasSig = false;
  canvas.classList.remove('has-sig');
}}

function submitSignature() {{
  const name = document.getElementById('signerName').value.trim();
  const err  = document.getElementById('errMsg');
  err.style.display = 'none';
  if (!name) {{ err.textContent = 'Please enter your full name.'; err.style.display = 'block'; return; }}
  if (!hasSig) {{ err.textContent = 'Please draw your signature above.'; err.style.display = 'block'; return; }}

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.textContent = 'Submitting…';

  const sigData = canvas.toDataURL('image/png');

  fetch('/sign/{token}', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ signer_name: name, signature_data: sigData }})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.ok) {{
      document.getElementById('formCard').style.display = 'none';
      document.getElementById('successCard').style.display = 'block';
    }} else {{
      err.textContent = d.error || 'Something went wrong. Please try again.';
      err.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Sign Document';
    }}
  }})
  .catch(() => {{
    err.textContent = 'Network error. Please check your connection and try again.';
    err.style.display = 'block';
    btn.disabled = false;
    btn.textContent = 'Sign Document';
  }});
}}

resizeCanvas();
window.addEventListener('resize', resizeCanvas);
</script>
</body>
</html>"""
