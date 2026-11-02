"""Human-readable inspection type names for emails, PDFs and signing pages.

One place so a type can never leak through as a raw value like "heads_up".
"""

_LABELS = {
    'inventory':     'Inventory',
    'check_in':      'Check In',
    'check_out':     'Check Out',
    'interim':       'Interim Inspection',
    'midterm':       'Midterm Inspection',
    'mid_term':      'Mid-Term Visit',
    'damage_report': 'Damage Report',
    'heads_up':      'Heads Up Report',
    'snagging':      'Snagging',
    'hhsrs':         'HHSRS',
}


def type_label(t):
    """Title for an inspection type, e.g. 'heads_up' -> 'Heads Up Report'."""
    key = (t or '').strip().lower().replace(' ', '_').replace('-', '_')
    if not key:
        return 'Inspection'
    return _LABELS.get(key) or key.replace('_', ' ').title()


def report_name(t):
    """Label that reads as a document name: 'Check In Report', 'Damage Report'
    (never 'Damage Report Report')."""
    label = type_label(t)
    return label if label.endswith('Report') else f'{label} Report'


def type_phrase(t):
    """Label for use before the word 'inspection' ('a Check In inspection',
    'a Midterm inspection') without doubling it up."""
    label = type_label(t)
    return label[:-len(' Inspection')] if label.endswith(' Inspection') else label
