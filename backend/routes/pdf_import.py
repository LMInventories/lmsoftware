"""
pdf_import.py — Parse a PDF inspection report with Claude.

Architecture: background thread + polling.
  POST /pdf-import  — accepts the PDF, starts a daemon thread, returns {job_id} immediately
                      (completes in < 1 second — immune to gunicorn worker timeouts)
  GET  /pdf-import-status/<job_id> — returns {status: processing|done|error, result?, error?, progress?}

The daemon thread calls Anthropic (no time pressure) and writes the result to a temp file.
Both gunicorn workers share the same filesystem, so any worker can serve the status poll.

Large PDF strategy:
  - Under CHUNK_THRESHOLD chars → single call with max_tokens=8192
  - Over threshold → split at room boundaries into chunks, process each separately,
    merge results server-side. This avoids JSON truncation for large inventories.
"""

import os
import io
import re
import json
import uuid
import base64
import threading
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

pdf_import_bp = Blueprint('pdf_import', __name__)

JOBS_DIR = '/tmp/pdf_import_jobs'
os.makedirs(JOBS_DIR, exist_ok=True)

MIN_TEXT_CHARS    = 500
CHUNK_THRESHOLD   = 14_000  # chars — above this we chunk
MAX_CHUNK_CHARS   = 10_000  # target chars per chunk
MAX_TOKENS_SINGLE = 16384   # generous ceiling for single calls
MAX_TOKENS_CHUNK  = 6144    # per-chunk ceiling
MIN_IMAGE_PX      = 100     # skip images smaller than 100 px in either dimension
MAX_IMAGES_TOTAL  = 150     # hard cap to avoid runaway S3 uploads

# Headings that indicate fixed/admin sections of a UK inventory report (not rooms).
# Images on pages whose first visible heading matches this pattern should NOT be
# assigned to any room — they go to the overview fallback.
_FIXED_SECTION_HEADING_RE = re.compile(
    r'^(keys?\b|keys?\s*(issued|handed|received|given|schedule)?'
    r'|utility\s+meter|meter\s+read|gas\s+meter|electricity\s+meter|electric'
    r'|water\s+meter|sub[- ]?meter|communal\s+meter'
    r'|cleaning\s*(summary|report|schedule|notes?)?'
    r'|condition\s+summary|overall\s+condition'
    r'|smoke|carbon|alarm|fire\s+door|health\s*(and|&)?\s*safety'
    r'|check[- ]?out\s+(summary|notes?)?'
    r'|schedule\s+of\s+condition)\s*$',
    re.IGNORECASE,
)

# Patterns used to extract photo reference numbers from PDF text near images,
# and to match those references in item description/condition text.
_REF_RE = re.compile(
    r'(?i)\bphoto[\s._#:\-]*(\d+)\b'
    r'|\bphot[\s._#:\-]*(\d+)\b'
    r'|\bref(?:erence)?[\s._#:\-]*(\d+)\b'
    r'|\bfig(?:ure)?[\s._#:\-]*(\d+)\b'
    r'|\bpic(?:ture)?[\s._#:\-]*(\d+)\b'
    r'|\bimg[\s._#:\-]*(\d+)\b'
    r'|^\s*(\d{1,3})\s*$',
)

# Room-like headings used to detect section boundaries in UK inventory reports
_ROOM_HEADER_RE = re.compile(
    r'^(?:HALLWAY|HALL|ENTRANCE|RECEPTION|LOUNGE|LIVING\s*ROOM|SITTING\s*ROOM|'
    r'KITCHEN|KITCHEN[/ ]*DINER|DINING\s*ROOM|BEDROOM|MASTER\s*BEDROOM|SPARE\s*BEDROOM|'
    r'BATHROOM|BATHROOM\s*\d|EN[- ]?SUITE|WC|TOILET|CLOAKROOM|LANDING|STAIRS?|'
    r'STAIRCASE|GARAGE|UTILITY\s*ROOM|STUDY|OFFICE|CONSERVATORY|GARDEN|LOFT|'
    r'CELLAR|BASEMENT|STORAGE|CUPBOARD|PORCH|LOBBY)[\s\d]*$',
    re.IGNORECASE,
)


def _page_text_spans(page):
    """Return list of (fitz.Rect, text_string) for all text spans on a page."""
    try:
        import fitz
        spans = []
        for block in page.get_text('dict').get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    txt = span.get('text', '').strip()
                    if txt:
                        spans.append((fitz.Rect(span['bbox']), txt))
        return spans
    except Exception:
        return []


def _extract_image_ref(page, xref, text_spans, margin=70):
    """
    Try to find a photo reference number in text near the image at xref on this page.
    margin is in PDF points (~25 mm at 72 dpi).
    Returns a normalised string like '1', '2', … or None.
    """
    try:
        img_rects = page.get_image_rects(xref)
        if not img_rects:
            return None
        ir = img_rects[0]
        candidates = []
        for span_rect, txt in text_spans:
            h_overlap = span_rect.x0 < ir.x1 + margin and span_rect.x1 > ir.x0 - margin
            v_near    = (ir.y0 - margin) < span_rect.y1 and span_rect.y0 < (ir.y1 + margin)
            if h_overlap and v_near:
                candidates.append(txt)
        for txt in candidates:
            m = _REF_RE.search(txt)
            if m:
                num = next(g for g in m.groups() if g is not None)
                return num.lstrip('0') or '0'
    except Exception:
        pass
    return None


PROMPT_TEMPLATE = """You are extracting structured data from a UK property inspection report (inventory or check-in) for a Check Out system.

Template structure to match against:
__TEMPLATE_STRUCTURE__

═══════════════════════════════════════
GOLDEN RULE — COPY & FORMAT
═══════════════════════════════════════
Copy text from the PDF VERBATIM into description and condition fields.
• Do NOT summarise, paraphrase, abbreviate, or reformat the content itself.
• Do NOT merge sentences or remove any words.
• Capitalise the first letter of each line; convert ALL-CAPS PDF text to Sentence case
  (e.g. "WHITE PAINTED PANEL DOOR" → "White painted panel door").
• Preserve already-mixed-case text verbatim (e.g. "uPVC" stays "uPVC").
• Preserve every detail exactly as written — this is a legal document.

═══════════════════════════════════════
LINE BREAKS
═══════════════════════════════════════
• Each physically distinct element gets its own line using \\n within the description string.
• Example: "White painted panel door\\nWhite painted door frame" (two separate physical elements).
• Comma-separated lists of DIFFERENT physical elements → split to \\n.
• But: "white painted, smooth finish" describing ONE element stays on one line.
• If the PDF spans multiple lines for one item, join them with \\n.

═══════════════════════════════════════
CONDITION IDENTIFICATION
═══════════════════════════════════════
These words signal CONDITION — split the text at the first condition word:
  everything before → description; everything from that word onwards → condition.

Condition signal words:
  In good order / good order / in fair order / in poor order / as new / as found / as inventory
  Scuff / scratch / mark / chip / crack / dent / stain / burn / peel / flake / warp
  Loose / tight / sticky / missing / broken / damaged / worn / fading / discoloured / mouldy
  Slight / minor / moderate / heavy / severe / light [defect word]
  Tested / working / not working
  Good clean condition / good condition / fair condition / poor condition

Examples:
  "White painted panel door. Good clean condition." → description: "White painted panel door", condition: "Good clean condition"
  "Carpet, beige twist pile. Minor wear to threshold." → description: "Carpet, beige twist pile", condition: "Minor wear to threshold"

═══════════════════════════════════════
COMPOUND ITEM SPLITTING
═══════════════════════════════════════
Many PDF reports use ONE heading for content that maps to MULTIPLE template items.
When you see a compound PDF heading, check the template for separate matching items and split:

  "Door/Frame/Fittings" or "Door, Frame & Fittings"
    → "Door & Frame" (panel + frame content) + "Door Fittings" (handles, locks, latches, hinges)

  "Walls & Ceiling" or "Walls/Ceiling"
    → "Walls" (wall surfaces) + "Ceiling" (ceiling surface)

  "Windows/Frame/Fittings" or "Window, Frame & Fittings"
    → "Windows" or "Window" (glazing, glass) + "Window Fittings" (handles, stays, locks, restrictors)

  "Floor/Skirting" or "Floor & Skirting"
    → "Floor" (floor covering) + "Skirting Board" or "Skirting" (skirting boards)

  "Light/Fittings" or "Light Fittings"
    → "Light Fittings" (single item — do NOT split unless template has distinct items)

Rule: If the template has only ONE matching item for a compound heading, do NOT split — put everything in that one item.
Rule: If the template has MULTIPLE matching items, distribute the relevant content to each.

═══════════════════════════════════════
MATCHING ALGORITHM — READ THIS CAREFULLY
═══════════════════════════════════════
Process the PDF line by line, for each room section:

1. Try to match the line to a template item label (case-insensitive, partial match OK).
   → If it matches: this line's data goes into that template item (label, description, condition).
      Remember this as the "current parent item".

2. If the line does NOT match any template item label:
   → It is a SUB-ITEM of the current parent item.
   → Add it to "_subs" on the current parent item.
   → Do NOT create a new top-level item for it.

3. Common sub-item patterns — these are ALWAYS sub-items, never top-level items:
   • "Contents - Bedside Table: Oak veneer / In good order"
     → parent = "Contents", sub = { description: "Bedside Table: Oak veneer", condition: "In good order" }
   • "Contents: Wardrobe — white gloss" followed by "In good order"
     → parent = "Contents", sub = { description: "Wardrobe — white gloss", condition: "In good order" }
   • Any line prefixed with the parent item name and a dash, colon, or slash

4. If NO template is provided (template says "No template"), infer structure from the PDF rooms/items directly — but still apply the sub-item rules above.

═══════════════════════════════════════
FIELD RULES
═══════════════════════════════════════
- label: EXACT label from the template where matched; otherwise use the PDF heading text, sentence-cased
- description: Verbatim from PDF, sentence-cased, multi-line elements joined with \\n. Empty string if not present.
- condition: Verbatim from PDF, sentence-cased (CHECK IN column only — ignore Check Out). Empty string if not present.
- _subs: Array present only when the item has sub-items. Each sub-item has only "description" and "condition" (both verbatim, sentence-cased).

═══════════════════════════════════════
FIXED SECTIONS
═══════════════════════════════════════
Extract these if present in the PDF. Copy all text verbatim (sentence-cased).
- condition_summary: overall condition notes
- keys: key types and quantities handed over (name = key type, description = quantity and cut type)
- meter_readings: gas/electric/water meter readings — SPLIT into three fields:
    • name: type of meter only (e.g. "Gas Meter", "Electricity Meter", "Water Meter")
    • locationSerial: WHERE the meter is located AND its serial number
      (e.g. "Under stairs cupboard\nSerial No: 1234567") — DO NOT put the reading here
    • reading: ONLY the numeric reading with unit (e.g. "12345.67 m³") — nothing else
- cleaning_summary: cleanliness notes

Return ONLY valid JSON — no markdown, no explanation:
{
  "rooms": [
    {
      "name": "Lounge",
      "items": [
        {
          "label": "Door & Frame",
          "description": "White painted solid panel door\\nWhite painted door frame",
          "condition": "Good clean condition throughout"
        },
        {
          "label": "Door Fittings",
          "description": "Chrome lever handle\\nChrome hinges x3",
          "condition": "Good order"
        },
        {
          "label": "Contents",
          "description": "",
          "condition": "",
          "_subs": [
            { "description": "Bedside table — oak veneer with single drawer", "condition": "Good order, minor surface scratch to top" },
            { "description": "Wardrobe — white gloss, double door with hanging rail", "condition": "Good clean condition" }
          ]
        }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [{ "name": "General Condition", "condition": "Good overall condition throughout" }],
    "keys": [{ "name": "Front Door Key", "description": "2 x Yale, 1 x Deadlock" }],
    "meter_readings": [{ "name": "Gas Meter", "locationSerial": "Under stairs cupboard\nSerial No: 1234567", "reading": "12345.67 m³" }],
    "cleaning_summary": [{ "name": "General Cleanliness", "cleanliness": "Professionally Cleaned", "cleanlinessNotes": "" }]
  }
}"""

CHUNK_PROMPT_TEMPLATE = """You are extracting structured data from a SECTION of a UK property inspection report (inventory or check-in).
This is one chunk of a larger document — extract every room and item you can find in this section.

Template structure (for label matching):
__TEMPLATE_STRUCTURE__

═══════════════════════════════════════
GOLDEN RULE — COPY & FORMAT
═══════════════════════════════════════
Copy text from the PDF VERBATIM into description and condition fields.
• Do NOT summarise, paraphrase, abbreviate, or reformat the content itself.
• Do NOT merge sentences or remove any words.
• Capitalise the first letter of each line; convert ALL-CAPS PDF text to Sentence case
  (e.g. "WHITE PAINTED PANEL DOOR" → "White painted panel door").
• Preserve already-mixed-case text verbatim (e.g. "uPVC" stays "uPVC").
• Preserve every detail exactly as written — this is a legal document.

═══════════════════════════════════════
LINE BREAKS
═══════════════════════════════════════
• Each physically distinct element gets its own line using \\n within the description string.
• Example: "White painted panel door\\nWhite painted door frame" (two separate physical elements).
• Comma-separated lists of DIFFERENT physical elements → split to \\n.
• But: "white painted, smooth finish" describing ONE element stays on one line.

═══════════════════════════════════════
CONDITION IDENTIFICATION
═══════════════════════════════════════
Split text at the first condition signal word:
  everything before → description; everything from that word onwards → condition.

Condition signal words:
  In good order / good order / in fair order / in poor order / as new / as found / as inventory
  Scuff / scratch / mark / chip / crack / dent / stain / burn / peel / flake / warp
  Loose / tight / sticky / missing / broken / damaged / worn / fading / discoloured / mouldy
  Slight / minor / moderate / heavy / severe / light [defect word]
  Tested / working / not working / good clean condition / good condition / fair condition / poor condition

═══════════════════════════════════════
COMPOUND ITEM SPLITTING
═══════════════════════════════════════
When you see a compound PDF heading, check the template for separate matching items and split:

  "Door/Frame/Fittings" or "Door, Frame & Fittings"
    → "Door & Frame" (panel + frame) + "Door Fittings" (handles, locks, latches)
  "Walls & Ceiling" or "Walls/Ceiling"
    → "Walls" (wall surfaces) + "Ceiling" (ceiling surface)
  "Windows/Frame/Fittings"
    → "Windows" (glazing) + "Window Fittings" (handles, stays, locks)
  "Floor/Skirting" or "Floor & Skirting"
    → "Floor" (floor covering) + "Skirting Board" (skirting boards)

If the template has only ONE matching item for a compound heading — do NOT split, put everything there.

═══════════════════════════════════════
HOW TO IDENTIFY ROOMS AND ITEMS
═══════════════════════════════════════
Room headings are typically short, standalone lines like:
  ENTRANCE HALL, LOUNGE, KITCHEN, BEDROOM 1, BATHROOM, EN-SUITE, LANDING, etc.
After a room heading, each distinct line or pair of lines is an ITEM within that room.

For each item:
- label: the item heading, sentence-cased (e.g. "Door & Frame", "Walls & Ceiling", "Floor", "Contents")
- description: text describing the item (material, colour, type) — verbatim, sentence-cased, multi-element → \\n
- condition: condition text from the CHECK IN column — verbatim, sentence-cased (ignore Check Out column)
- _subs: if the item has sub-entries listed beneath it (e.g. individual contents items), put each as { description, condition }

If a line starts with the parent item name followed by a dash, colon, or slash, it is a sub-item:
  "Contents - Bedside Table: Oak veneer / In good order"
  → parent = "Contents", sub = { description: "Bedside table — oak veneer", condition: "In good order" }

═══════════════════════════════════════
FIXED SECTIONS
═══════════════════════════════════════
If you see any of these sections in the text, extract them too:
- Keys handed over → fixedSections.keys
  Each entry: { "name": "key type", "description": "quantity and cut, e.g. 2 x Yale" }
- Meter readings (gas/electric/water) → fixedSections.meter_readings
  SPLIT each reading into three fields — do NOT put location or serial info into "reading":
  { "name": "Gas Meter", "locationSerial": "Under stairs cupboard\nSerial No: 1234567", "reading": "12345.67 m³" }
  • name: type of meter only
  • locationSerial: location description + serial number (on separate lines if both present)
  • reading: the numeric reading + unit ONLY
- Overall condition notes → fixedSections.condition_summary
- Cleanliness notes → fixedSections.cleaning_summary

Return ONLY valid JSON — no markdown, no explanation, no trailing text:
{
  "rooms": [
    {
      "name": "Entrance Hall",
      "items": [
        { "label": "Door & Frame", "description": "White painted solid panel door\\nWhite painted door frame", "condition": "Good clean condition" },
        { "label": "Door Fittings", "description": "Chrome lever handle\\nChrome hinges x3", "condition": "Good order" },
        { "label": "Walls & Ceiling", "description": "Painted white throughout\\nSmooth plaster ceiling", "condition": "Good order, minor scuff to wall near door" },
        { "label": "Contents", "description": "", "condition": "",
          "_subs": [
            { "description": "Coat hooks x4 — chrome", "condition": "Good order" }
          ]
        }
      ]
    }
  ],
  "fixedSections": {
    "condition_summary": [],
    "keys": [],
    "meter_readings": [],
    "cleaning_summary": []
  }
}

PDF TEXT SECTION:
__CHUNK_TEXT__"""


# ── Job file helpers ──────────────────────────────────────────────────────────

def _job_path(job_id):
    return os.path.join(JOBS_DIR, job_id + '.json')

def _write_job(job_id, data):
    with open(_job_path(job_id), 'w') as f:
        json.dump(data, f)

def _read_job(job_id):
    path = _job_path(job_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)

def _delete_job(job_id):
    try:
        os.remove(_job_path(job_id))
    except OSError:
        pass


# ── PDF text extraction ───────────────────────────────────────────────────────

def _extract_pdf_text_by_page(raw_bytes):
    """Returns {page_num (0-based): text} using pdfplumber."""
    try:
        import pdfplumber
        page_texts = {}
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text(x_tolerance=3, y_tolerance=3)
                if t:
                    page_texts[i] = t
        return page_texts
    except Exception as e:
        print('[pdf-import] pdfplumber failed: ' + str(e))
        return {}


def _extract_pdf_text(raw_bytes):
    page_texts = _extract_pdf_text_by_page(raw_bytes)
    return '\n'.join(page_texts[i] for i in sorted(page_texts))


# ── PDF image extraction ──────────────────────────────────────────────────────

def _extract_pdf_images(raw_bytes, job_id):
    """
    Extract embedded images from a PDF and upload to S3.

    Returns:
      page_images : {page_num (0-based): [{'url': str, 'ref': str|None}, ...]}
      cover_photo : str | None  — URL of the property overview / cover photo

    Logo / decorative image filtering:
      • Images that appear on 3+ pages (e.g. repeated header logos) are skipped.
      • Images with a transparent soft mask (smask > 0) are skipped — most agent
        logos are PNG-with-transparency; real property photos are opaque JPEGs.
      • Images with extreme aspect ratios (>5:1 or <1:5) are skipped.

    Cover photo identification:
      The first sufficiently large opaque image on page 0 is treated as the
      property / cover photo and returned separately (not added to page_images).
    """
    try:
        from utils.s3 import is_configured, upload_bytes, new_key
        if not is_configured():
            return {}, None
    except Exception:
        return {}, None

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print('[pdf-import] PyMuPDF not installed — skipping image extraction')
        return {}, None

    page_images = {}
    cover_photo = None
    seen_xrefs  = set()
    total       = 0
    prefix      = f'pdf-import/{job_id}'

    try:
        doc = fitz.open(stream=raw_bytes, filetype='pdf')

        # Pre-scan: count how many pages each image xref appears on.
        # xrefs seen on 3+ pages are repeated elements (headers, logos) — skip them.
        xref_page_count: dict = {}
        for pn in range(len(doc)):
            for im in doc[pn].get_images():
                xref_page_count[im[0]] = xref_page_count.get(im[0], 0) + 1

        for page_num in range(len(doc)):
            if total >= MAX_IMAGES_TOTAL:
                break
            page       = doc[page_num]
            img_list   = page.get_images(full=True)
            text_spans = _page_text_spans(page)
            entries    = []
            for img in img_list:
                if total >= MAX_IMAGES_TOTAL:
                    break
                xref  = img[0]
                smask = img[1]   # soft-mask xref; > 0 means the image has transparency
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                # Skip repeated elements (logos on every page header/footer)
                if xref_page_count.get(xref, 1) >= 3:
                    continue

                # Skip transparent images — agent logos are almost always PNG-with-alpha;
                # real room / property photos are typically opaque JPEGs.
                if smask > 0:
                    continue

                try:
                    base_image = doc.extract_image(xref)
                    w = base_image.get('width',  0)
                    h = base_image.get('height', 0)
                    if w < MIN_IMAGE_PX or h < MIN_IMAGE_PX:
                        continue

                    # Skip extreme aspect ratios (banner logos, thin decorative elements)
                    aspect = w / h if h > 0 else 1.0
                    if aspect > 5.0 or aspect < 0.2:
                        continue

                    img_bytes = base_image['image']
                    ext       = base_image.get('ext', 'jpeg')
                    ctype     = 'image/jpeg' if ext in ('jpeg', 'jpg') else f'image/{ext}'
                    key       = new_key(prefix, ext)
                    url       = upload_bytes(img_bytes, key, ctype)
                    total    += 1

                    # First large image on page 0 = property cover photo
                    if page_num == 0 and cover_photo is None and w >= 300 and h >= 200:
                        cover_photo = url
                        continue   # don't add to room images

                    img_y = None
                    try:
                        ir_list = page.get_image_rects(xref)
                        if ir_list:
                            img_y = ir_list[0].y0
                    except Exception:
                        pass
                    ref = _extract_image_ref(page, xref, text_spans)
                    entries.append({'url': url, 'ref': ref, 'y': img_y})
                except Exception as e:
                    print(f'[pdf-import] image xref {xref} extract error: {e}')
            if entries:
                page_images[page_num] = entries
        doc.close()
    except Exception as e:
        print(f'[pdf-import] image extraction error: {e}')

    return page_images, cover_photo


def _norm_room(s):
    """Normalise a room name to bare alphanumeric for fuzzy matching."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _is_fixed_section_page(text):
    """
    Return True if the page text starts with a fixed/admin section heading
    (keys, meter readings, cleaning summary, etc.) rather than a room heading.
    Only checks the first few lines to avoid false positives from body text.
    """
    for line in text.splitlines()[:8]:
        stripped = line.strip()
        if stripped and _FIXED_SECTION_HEADING_RE.match(stripped):
            return True
    return False


def _room_name_on_page(rname_norm, page_text):
    """
    Return True if the page text contains a line that IS the room name.

    Matching rules (tight, to avoid false positives from item descriptions):
      1. Normalised line == normalised room name  (exact)
      2. Normalised line STARTS WITH the room name and the extra suffix is short
         (≤ 20 chars after stripping) — handles "Bedroom 1 (Ground Floor)" etc.

    Deliberately excludes substring matches like 'kitchen' appearing inside
    "adjacent to the kitchen area", which caused systematic off-by-one errors.

    Only the first 20 lines of the page are checked — room headings are always
    near the top of a section, not buried in item descriptions.
    """
    for line in page_text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        line_norm = _norm_room(stripped)
        if not line_norm:
            continue
        if line_norm == rname_norm:
            return True
        if (line_norm.startswith(rname_norm)
                and len(line_norm) <= len(rname_norm) + 20):
            return True
    return False


def _find_room_positions(raw_bytes, page_texts, room_names):
    """
    Use PyMuPDF text spans to find (page_num, y0) for each room heading.
    Returns {rname: (page_num, y0)} — rooms not found are absent from the dict.
    Falls back gracefully if PyMuPDF is unavailable.
    """
    try:
        import fitz
    except ImportError:
        return {}

    result = {}
    doc = None
    try:
        doc = fitz.open(stream=raw_bytes, filetype='pdf')

        # Pre-scan all pages once — avoids rescanning per room
        page_span_data = {}
        for pn in range(len(doc)):
            spans = _page_text_spans(doc[pn])
            filtered = []
            for rect, txt in spans:
                stripped = txt.strip()
                if stripped and len(stripped) <= 80:
                    filtered.append((rect, stripped, _norm_room(stripped)))
            page_span_data[pn] = filtered

        for room in room_names:
            rname = room.get('name', '')
            if not rname:
                continue
            rname_norm = _norm_room(rname)
            if not rname_norm:
                continue
            for pn in range(len(doc)):
                for rect, txt, txt_norm in page_span_data.get(pn, []):
                    if not txt_norm:
                        continue
                    if (txt_norm == rname_norm or
                            (txt_norm.startswith(rname_norm)
                             and len(txt_norm) <= len(rname_norm) + 20)):
                        result[rname] = (pn, rect.y0)
                        break
                if rname in result:
                    break
    except Exception as e:
        print(f'[pdf-import] _find_room_positions: {e}')
    finally:
        if doc:
            try:
                doc.close()
            except Exception:
                pass

    return result


def _map_images_to_rooms(page_texts, page_images, claude_rooms=None, room_positions=None):
    """
    Associate extracted images with rooms using page-order heuristic.

    Algorithm (when claude_rooms is supplied):
      1. For each Claude room, search pages INDEPENDENTLY to find the first page
         where that room's name appears as a headline (tight matching — exact or
         starts-with only; no substring-in-sentence matches).
      2. Sort rooms by their first-page and walk all pages, updating current_room
         at each room transition.
      3. Pages whose first heading matches a fixed-section keyword (keys, meters,
         cleaning, etc.) have their images sent to `unmatched` regardless of
         current_room — prevents meter/key photos landing in the last room.

    Falls back to the regex-based _ROOM_HEADER_RE heuristic if no Claude room
    names can be located in the page texts.

    Returns:
      room_photos : {room_name: [{'url': str, 'ref': str|None}, ...]}
      unmatched   : [{'url': str, 'ref': str|None}]  — photos with no room
    """
    if not page_images:
        return {}, []

    all_pages        = sorted(set(list(page_texts.keys()) + list(page_images.keys())))
    sorted_page_nums = sorted(page_texts.keys())

    # ── Claude-based mapping ──────────────────────────────────────────────
    if claude_rooms:
        # Step 1: find the FIRST page for each room.
        # Prefer room_positions (PyMuPDF span coords — most accurate).
        # Fall back to text-scan via _room_name_on_page for any rooms not found.
        room_first_page: dict = {}

        if room_positions:
            room_first_page = {rname: pn for rname, (pn, _) in room_positions.items()}

        for room in claude_rooms:
            rname = room.get('name', '')
            if not rname or rname in room_first_page:
                continue
            rname_norm = _norm_room(rname)
            if not rname_norm:
                continue
            for page_num in sorted_page_nums:
                if _room_name_on_page(rname_norm, page_texts[page_num]):
                    room_first_page[rname] = page_num
                    break

        if room_first_page:
            # Step 2: sort by start page, then assign images page by page.
            sorted_starts = sorted(room_first_page.items(), key=lambda x: x[1])
            current_room  = None
            room_photos: dict = {}
            unmatched     = []
            starts_idx    = 0

            for page_num in all_pages:
                # Save room active before this page so images above the first
                # heading on this page are correctly assigned to the prior room.
                prev_room = current_room

                # Advance current_room to the latest room whose start ≤ this page
                while (starts_idx < len(sorted_starts)
                       and sorted_starts[starts_idx][1] <= page_num):
                    current_room = sorted_starts[starts_idx][0]
                    starts_idx  += 1

                entries = page_images.get(page_num, [])
                if not entries:
                    continue

                # If this page is a fixed/admin section (keys, meters, etc.),
                # don't assign its images to any room — send to overview fallback.
                page_text = page_texts.get(page_num, '')
                if page_text and _is_fixed_section_page(page_text):
                    unmatched.extend(entries)
                    continue

                # Within-page splitting: when we know y-coords of room headings
                # on this page, assign each image to the room whose heading it
                # appears after vertically (y increases downward in PyMuPDF).
                if room_positions:
                    page_room_ys = sorted(
                        [(rn, y) for rn, (pn, y) in room_positions.items()
                         if pn == page_num and y is not None],
                        key=lambda x: x[1],
                    )
                    if page_room_ys:
                        for entry in entries:
                            ey = entry.get('y')
                            if ey is None:
                                assigned = current_room
                            else:
                                # Images above the first heading on this page
                                # belong to the room that was active on the prior page.
                                assigned = prev_room
                                for rn, ry in page_room_ys:
                                    if ey >= ry:
                                        assigned = rn
                                    else:
                                        break
                            if assigned:
                                room_photos.setdefault(assigned, []).append(entry)
                            else:
                                unmatched.append(entry)
                        continue

                if current_room:
                    room_photos.setdefault(current_room, []).extend(entries)
                else:
                    unmatched.extend(entries)

            return room_photos, unmatched

    # ── Regex fallback (no Claude rooms or none found in text) ────────────
    current_room = None
    room_photos  = {}
    unmatched    = []
    for page_num in all_pages:
        text = page_texts.get(page_num, '')
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and _ROOM_HEADER_RE.match(stripped):
                current_room = stripped.title()
                break
        entries = page_images.get(page_num, [])
        if not entries:
            continue
        if current_room:
            room_photos.setdefault(current_room, []).extend(entries)
        else:
            unmatched.extend(entries)

    return room_photos, unmatched


# ── Text chunking ─────────────────────────────────────────────────────────────

def _split_into_chunks(text, max_chars=MAX_CHUNK_CHARS):
    """
    Split extracted PDF text into chunks, trying to break at room/section
    boundaries so each chunk is self-contained. Falls back to hard splits
    at paragraph breaks if no room header is found within a window.
    """
    lines = text.split('\n')
    chunks = []
    current_lines = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1

        # If we're over the limit, try to cut here if this line looks like a room heading
        if current_size + line_size > max_chars and current_lines:
            is_boundary = (
                _ROOM_HEADER_RE.match(line.strip())
                or (line.strip() == '' and current_size > max_chars * 0.6)
            )
            if is_boundary:
                chunks.append('\n'.join(current_lines))
                current_lines = [line] if line.strip() else []
                current_size = line_size if line.strip() else 0
                continue

        # Hard split if we're way over
        if current_size + line_size > max_chars * 1.5 and current_lines:
            chunks.append('\n'.join(current_lines))
            current_lines = [line]
            current_size = line_size
            continue

        current_lines.append(line)
        current_size += line_size

    if current_lines:
        chunks.append('\n'.join(current_lines))

    # Filter out trivially small chunks (page headers/footers only)
    return [c for c in chunks if len(c.strip()) > 100]


# ── Claude call helpers ───────────────────────────────────────────────────────

def _call_claude(client, messages, max_tokens):
    """Single Claude call, returns parsed JSON dict or raises."""
    response = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=max_tokens,
        messages=messages,
    )
    raw = response.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(raw)


def _merge_results(results):
    """Merge a list of {rooms, fixedSections} dicts into one."""
    merged_rooms = []
    merged_fixed = {
        'condition_summary': [],
        'keys': [],
        'meter_readings': [],
        'cleaning_summary': [],
    }

    seen_room_names = {}  # name.lower() → index in merged_rooms

    for result in results:
        for room in result.get('rooms', []):
            name_key = room.get('name', '').lower().strip()
            if name_key in seen_room_names:
                # Merge items into the existing room entry
                idx = seen_room_names[name_key]
                merged_rooms[idx]['items'].extend(room.get('items', []))
            else:
                seen_room_names[name_key] = len(merged_rooms)
                merged_rooms.append({
                    'name': room.get('name', ''),
                    'items': list(room.get('items', [])),
                })

        fs = result.get('fixedSections', {})
        for key in merged_fixed:
            items = fs.get(key, [])
            if items:
                merged_fixed[key].extend(items)

    return {'rooms': merged_rooms, 'fixedSections': merged_fixed}


# ── Background worker ─────────────────────────────────────────────────────────

def _run_import_job(job_id, api_key, extracted_text, pdf_b64, template_structure,
                    use_text_mode, inspection_id, filename,
                    page_texts=None, raw_bytes=None):
    """Runs in a daemon thread. Writes result to a temp file when complete."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)

        # ── Image extraction (before Claude, mapping deferred until after) ────
        # S3 uploads happen here before the long Claude call.
        # Room mapping is done AFTER Claude so we can use Claude's room names.
        page_images     = {}
        cover_photo_url = None
        if raw_bytes:
            try:
                _write_job(job_id, {
                    'status':        'processing',
                    'progress':      'Extracting photos…',
                    'inspection_id': inspection_id,
                    'filename':      filename,
                })
                page_images, cover_photo_url = _extract_pdf_images(raw_bytes, job_id)
                img_count = sum(len(v) for v in page_images.values())
                print(f'[pdf-import] job {job_id}: extracted {img_count} images, '
                      f'cover={cover_photo_url is not None}')
            except Exception as img_e:
                print(f'[pdf-import] job {job_id} image extraction error: {img_e}')

        if not use_text_mode:
            # Document mode: send raw PDF — no chunking possible
            print('[pdf-import] job ' + job_id + ' document mode (single call)')
            _write_job(job_id, {
                'status': 'processing',
                'progress': 'Analysing PDF with AI…',
                'inspection_id': inspection_id,
                'filename': filename,
            })
            prompt = PROMPT_TEMPLATE.replace('__TEMPLATE_STRUCTURE__', template_structure)
            messages = [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': pdf_b64}},
                        {'type': 'text', 'text': prompt},
                    ],
                }
            ]
            parsed = _call_claude(client, messages, MAX_TOKENS_SINGLE)

        elif len(extracted_text) <= CHUNK_THRESHOLD:
            # Small PDF — single call
            print('[pdf-import] job ' + job_id + ' text mode, single call (' + str(len(extracted_text)) + ' chars)')
            _write_job(job_id, {
                'status': 'processing',
                'progress': 'Analysing PDF with AI…',
                'inspection_id': inspection_id,
                'filename': filename,
            })
            prompt = PROMPT_TEMPLATE.replace('__TEMPLATE_STRUCTURE__', template_structure)
            messages = [{'role': 'user', 'content': prompt + '\n\n---\nPDF TEXT CONTENT:\n' + extracted_text}]
            parsed = _call_claude(client, messages, MAX_TOKENS_SINGLE)

        else:
            # Large PDF — split into chunks and merge
            chunks = _split_into_chunks(extracted_text)
            print('[pdf-import] job ' + job_id + ' text mode, chunked: ' + str(len(chunks)) + ' chunks from ' + str(len(extracted_text)) + ' chars')

            results = []
            for i, chunk in enumerate(chunks):
                print('[pdf-import] job ' + job_id + ' chunk ' + str(i + 1) + '/' + str(len(chunks)) + ' (' + str(len(chunk)) + ' chars)')
                _write_job(job_id, {
                    'status': 'processing',
                    'progress': 'Analysing chunk ' + str(i + 1) + ' of ' + str(len(chunks)) + '…',
                    'inspection_id': inspection_id,
                    'filename': filename,
                })
                chunk_prompt = (
                    CHUNK_PROMPT_TEMPLATE
                    .replace('__TEMPLATE_STRUCTURE__', template_structure)
                    .replace('__CHUNK_TEXT__', chunk)
                )
                messages = [{'role': 'user', 'content': chunk_prompt}]
                try:
                    chunk_result = _call_claude(client, messages, MAX_TOKENS_CHUNK)
                    chunk_rooms = len(chunk_result.get('rooms', []))
                    chunk_items = sum(len(r.get('items', [])) for r in chunk_result.get('rooms', []))
                    print('[pdf-import] job ' + job_id + ' chunk ' + str(i + 1) + ' → ' + str(chunk_rooms) + ' rooms, ' + str(chunk_items) + ' items')
                    results.append(chunk_result)
                except json.JSONDecodeError as e:
                    print('[pdf-import] job ' + job_id + ' chunk ' + str(i + 1) + ' JSON error (skipping): ' + str(e))
                    # Skip bad chunks rather than failing the whole job
                    continue

            if not results:
                raise ValueError('All chunks failed to parse — no usable data extracted')

            parsed = _merge_results(results)

        # ── Map images to rooms using Claude's room names (most reliable) ───
        # Done AFTER Claude so we can use the actual room names Claude extracted,
        # rather than guessing from regex on raw PDF text.
        room_photos     = {}
        overview_photos = []
        if page_images:
            try:
                pt = page_texts or {}
                # Use PyMuPDF span coordinates to find exact room heading positions.
                # This lets us split photos on multi-room pages by y-coordinate.
                room_positions = {}
                if raw_bytes and parsed.get('rooms'):
                    try:
                        room_positions = _find_room_positions(raw_bytes, pt, parsed['rooms'])
                        print(f'[pdf-import] job {job_id}: located {len(room_positions)} '
                              f'room positions via spans')
                    except Exception as pos_e:
                        print(f'[pdf-import] job {job_id} room position detection: {pos_e}')

                room_photos, overview_photos = _map_images_to_rooms(
                    pt, page_images, parsed.get('rooms', []),
                    room_positions=room_positions,
                )
                total = sum(len(v) for v in room_photos.values()) + len(overview_photos)
                print(f'[pdf-import] job {job_id}: mapped {total} photos → '
                      f'{len(room_photos)} rooms, {len(overview_photos)} unmatched')
            except Exception as map_e:
                print(f'[pdf-import] job {job_id} photo mapping error: {map_e}')

        # ── Attach photos to parsed rooms ─────────────────────────────────
        if room_photos or overview_photos:
            for room in parsed.get('rooms', []):
                rname = room.get('name', '')
                photos = room_photos.get(rname)
                if not photos:
                    # Normalised fallback — handles case/punctuation differences
                    rname_norm = _norm_room(rname)
                    for rk, rp in room_photos.items():
                        if _norm_room(rk) == rname_norm:
                            photos = rp
                            break
                if photos:
                    room['_photos']    = [p['url'] for p in photos]
                    room['_photoRefs'] = [p.get('ref') for p in photos]

            # Photos before any room heading go to the overview fallback
            if overview_photos:
                parsed['_overviewPhotos'] = [p['url'] for p in overview_photos]

        # Cover photo (first large opaque image on page 0)
        if cover_photo_url:
            parsed['_coverPhoto'] = cover_photo_url

        room_count  = len(parsed.get('rooms', []))
        item_count  = sum(len(r.get('items', [])) for r in parsed.get('rooms', []))
        photo_count = sum(len(r.get('_photos', [])) for r in parsed.get('rooms', []))
        mode = 'text' if use_text_mode else 'document'
        print('[pdf-import] job ' + job_id + ' done: ' + str(room_count) + ' rooms, '
              + str(item_count) + ' items, ' + str(photo_count) + ' photos, '
              + ('cover=yes' if cover_photo_url else 'cover=no') + ' (mode=' + mode + ')')

        _write_job(job_id, {
            'status': 'done',
            'result': parsed,
            'inspection_id': inspection_id,
            'filename': filename,
        })

    except json.JSONDecodeError as e:
        print('[pdf-import] job ' + job_id + ' JSON error: ' + str(e))
        _write_job(job_id, {
            'status': 'error',
            'error': 'Claude returned invalid JSON: ' + str(e),
            'inspection_id': inspection_id,
            'filename': filename,
        })

    except Exception as e:
        import traceback
        print('[pdf-import] job ' + job_id + ' error: ' + str(e))
        print(traceback.format_exc())
        _write_job(job_id, {
            'status': 'error',
            'error': str(e),
            'inspection_id': inspection_id,
            'filename': filename,
        })


# ── Routes ────────────────────────────────────────────────────────────────────

@pdf_import_bp.route('/pdf-import', methods=['POST'])
@jwt_required()
def pdf_import():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # Accept multipart/form-data or legacy JSON
    raw_bytes = None
    pdf_b64 = None

    if request.content_type and 'multipart/form-data' in request.content_type:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file_obj = request.files['file']
        raw_bytes = file_obj.read()
        if not raw_bytes:
            return jsonify({'error': 'Uploaded file is empty'}), 400
        template_structure = request.form.get('templateStructure') or 'No template - infer structure from PDF'
        inspection_id = request.form.get('inspectionId') or ''
        filename = file_obj.filename or 'report.pdf'
        print('[pdf-import] received file via multipart: ' + repr(filename) + ', ' + str(len(raw_bytes)) + ' bytes, inspection_id=' + repr(inspection_id))
    else:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        pdf_b64 = data.get('pdf')
        template_structure = data.get('templateStructure') or 'No template - infer structure from PDF'
        inspection_id = data.get('inspectionId') or ''
        filename = data.get('filename') or 'report.pdf'
        if not pdf_b64:
            return jsonify({'error': 'No PDF data provided'}), 400
        raw_bytes = base64.b64decode(pdf_b64)

    # Text extraction (page-by-page so the thread can use it for photo mapping)
    page_texts     = _extract_pdf_text_by_page(raw_bytes)
    extracted_text = '\n'.join(page_texts[i] for i in sorted(page_texts))
    use_text_mode  = len(extracted_text) >= MIN_TEXT_CHARS

    if not use_text_mode and pdf_b64 is None:
        pdf_b64 = base64.b64encode(raw_bytes).decode('utf-8')

    # Start background job and return immediately
    job_id = str(uuid.uuid4())
    _write_job(job_id, {
        'status': 'processing',
        'progress': 'Starting…',
        'inspection_id': inspection_id,
        'filename': filename,
    })

    thread = threading.Thread(
        target=_run_import_job,
        args=(job_id, api_key, extracted_text, pdf_b64, template_structure,
              use_text_mode, inspection_id, filename, page_texts, raw_bytes),
        daemon=True,
    )
    thread.start()

    print('[pdf-import] started job ' + job_id + ' (text_len=' + str(len(extracted_text)) + ', chunked=' + str(len(extracted_text) > CHUNK_THRESHOLD) + ')')
    return jsonify({'job_id': job_id})


@pdf_import_bp.route('/pdf-import-status/<job_id>', methods=['GET'])
@jwt_required()
def pdf_import_status(job_id):
    # Validate job_id looks like a UUID
    if not job_id or len(job_id) > 40:
        return jsonify({'error': 'Invalid job ID'}), 400

    job = _read_job(job_id)
    if not job:
        return jsonify({'status': 'not_found'}), 404

    status = job.get('status')
    if status == 'processing':
        return jsonify({
            'status': 'processing',
            'progress': job.get('progress', ''),
            'inspection_id': job.get('inspection_id', ''),
            'filename': job.get('filename', ''),
        })
    elif status == 'done':
        _delete_job(job_id)
        return jsonify({
            'status': 'done',
            'result': job['result'],
            'inspection_id': job.get('inspection_id', ''),
            'filename': job.get('filename', ''),
        })
    else:
        _delete_job(job_id)
        return jsonify({
            'status': 'error',
            'error': job.get('error', 'Unknown error'),
            'inspection_id': job.get('inspection_id', ''),
            'filename': job.get('filename', ''),
        })
