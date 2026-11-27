"""Master sheet sync, against an in-memory stand-in for the Google Sheets API.

Two layouts: the original single (first) tab, and one tab per year, switched on by
"YEAR TABS | ON" on the Settings tab."""
import copy
import io
import json
import re
import urllib.error
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from services import google_sheets as gs

HEADER = ['Client', 'Clerk', 'Date', 'Reference', 'Address', 'Job', 'Size', 'Fee', 'Typing', 'InvoicePaid?']


def _column(letters):
    return ord(letters) - ord('A')


class FakeSheet:
    def __init__(self, tabs):
        """tabs: [(title, rows)] in tab order; rows exclude the header."""
        self.tabs = [{'title': title, 'sheetId': 100 + i, 'rows': [list(HEADER)] + [list(r) for r in rows],
                      'rowCount': 50} for i, (title, rows) in enumerate(tabs)]
        self.writes = []
        self.reads = []
        self.fail = None

    def tab(self, title):
        return next(t for t in self.tabs if t['title'] == title)

    def rows(self, title):
        """Data rows (without header) that hold anything."""
        return [r for r in self.tab(title)['rows'][1:] if any(str(c) != '' for c in r)]

    def _split(self, a1):
        match = re.fullmatch(r"(?:'?(?P<tab>[^'!]+)'?!)?(?P<c1>[A-Z])(?P<r1>\d*)(?::(?P<c2>[A-Z])(?P<r2>\d*))?", a1)
        assert match, a1
        tab = self.tab(match['tab']) if match['tab'] else self.tabs[0]
        return tab, match

    def values(self, a1):
        tab, m = self._split(a1)
        c1, c2 = _column(m['c1']), _column(m['c2'] or m['c1'])
        rows = tab['rows']
        if m['r1']:
            rows = rows[int(m['r1']) - 1:int(m['r2'] or m['r1'])]
        out = []
        for row in rows:
            cells = [('TRUE' if c else 'FALSE') if isinstance(c, bool) else c for c in row[c1:c2 + 1]]
            while cells and cells[-1] == '':
                cells.pop()
            out.append(cells)
        while out and not out[-1]:
            out.pop()
        return out

    def put(self, a1, values):
        tab, m = self._split(a1)
        row, col = int(m['r1']) - 1, _column(m['c1'])
        while len(tab['rows']) <= row:
            tab['rows'].append([])
        target = tab['rows'][row]
        target.extend([''] * max(0, col + len(values[0]) - len(target)))
        target[col:col + len(values[0])] = values[0]

    def batch(self, requests):
        by_id = {t['sheetId']: t for t in self.tabs}
        for request in requests:
            if 'appendDimension' in request:
                r = request['appendDimension']
                by_id[r['sheetId']]['rowCount'] += r['length']
            elif 'copyPaste' in request:
                source, dest = request['copyPaste']['source'], request['copyPaste']['destination']
                assert dest['endRowIndex'] <= by_id[dest['sheetId']]['rowCount'], 'outside the grid'
                row = copy.copy(by_id[source['sheetId']]['rows'][source['startRowIndex']])
                rows = by_id[dest['sheetId']]['rows']
                while len(rows) <= dest['startRowIndex']:
                    rows.append([])
                rows[dest['startRowIndex']] = row
            else:
                r = request['deleteDimension']['range']
                del by_id[r['sheetId']]['rows'][r['startIndex']:r['endIndex']]

    def urlopen(self, req, timeout=None):
        url = urlsplit(req.full_url)
        path = url.path.split('/spreadsheets/', 1)[1]
        method = req.get_method()
        if self.fail and self.fail in unquote(req.full_url):
            raise urllib.error.HTTPError(req.full_url, 500, 'boom', {}, io.BytesIO(b'boom'))
        (self.reads if method == 'GET' else self.writes).append((method, unquote(path), unquote(url.query)))
        if path.endswith(':batchUpdate'):
            self.batch(json.loads(req.data)['requests'])
            body = {}
        elif path.endswith('/values:batchGet'):
            body = {'valueRanges': [{'values': self.values(r)} for r in parse_qs(url.query)['ranges']]}
        elif '/values/' in path:
            a1 = unquote(path.split('/values/', 1)[1])
            if method == 'PUT':
                self.put(a1, json.loads(req.data)['values'])
                body = {'updatedRange': a1}
            else:
                body = {'values': self.values(a1)}
        else:
            body = {'sheets': [{'properties': {'sheetId': t['sheetId'], 'title': t['title'],
                                               'gridProperties': {'rowCount': t['rowCount']}}} for t in self.tabs]}
        return io.BytesIO(json.dumps(body).encode())


def _row(ref, when, insp_id='', fee=120, paid='', flags=None, address='1 High Street', job='Check Out'):
    row = ['Yellands', 'Robyn', when, ref, address, job, '1', fee, '', paid, str(insp_id)]
    if flags:
        row += [''] * (23 - len(row)) + list(flags)
    return row


def _inspection(insp_id=7, when=datetime(2026, 11, 20), ref='INS-7', kind='check_out'):
    client = SimpleNamespace(company='Yellands Estates', name='Contact', report_photo_settings=None)
    prop = SimpleNamespace(client=client, address='1 High Street', bedrooms=1)
    return SimpleNamespace(id=insp_id, inspection_type=kind, property=prop, reference_number=ref,
                           inspector=SimpleNamespace(name='Robyn'), conduct_date=when, scheduled_date=None,
                           pdf_import=False, source_inspection_id=None)


@pytest.fixture()
def connect(monkeypatch):
    def use(sheet):
        monkeypatch.setattr(gs.urllib.request, 'urlopen', sheet.urlopen)
        monkeypatch.setattr(gs, '_get_sheet_id', lambda: 'sheet')
        import routes.google
        monkeypatch.setattr(routes.google, 'get_valid_access_token', lambda: 'token')
        return sheet
    return use


def _years(rows_2025=(), rows_2026=(), rows_2027=(), switch='ON'):
    sheet = FakeSheet([('Dashboard', []), ('2025', rows_2025), ('2026', rows_2026), ('2027', rows_2027),
                       ('Settings', [])])
    sheet.tab('Settings')['rows'] = [['TEST MODE', 'OFF'], ['YEAR TABS', switch]]
    return sheet


# ── Not split by year: as before ────────────────────────────────────────────

@pytest.mark.parametrize('settings', [None, [['TEST MODE', 'OFF']], [['TEST MODE', 'OFF'], ['YEAR TABS', 'OFF']]])
def test_off_writes_to_the_first_tab(connect, settings):
    tabs = [('2025', [_row('A1', '01/05/2025')]), ('2027', [])]
    sheet = connect(FakeSheet(tabs + ([('Settings', [])] if settings else [])))
    if settings:
        sheet.tab('Settings')['rows'] = settings
    assert gs.sync_inspection_row(_inspection(when=datetime(2027, 1, 5))) == (True, None)
    added = sheet.rows('2025')[-1]
    assert added[:7] == ['Yellands', 'Robyn', '05/01/2027', 'INS-7', '1 High Street', 'Check Out', '1']
    assert added[10] == '7' and sheet.rows('2027') == []
    assert gs.write_invoice_paid(_inspection(), True)[0] and sheet.rows('2025')[-1][9] == 'YES'
    assert gs.write_invoice_paid(_inspection(), False)[0] and sheet.rows('2025')[-1][9] == ''
    assert gs.get_existing_reference_numbers() == ({'a1', 'ins-7'}, None)
    assert gs.delete_inspection_row(_inspection())[0] and len(sheet.rows('2025')) == 1


def test_off_refuses_to_write_over_a_dashboard(connect):
    sheet = connect(_years(switch='OFF'))
    ok, error = gs.sync_inspection_row(_inspection())
    assert not ok and 'YEAR TABS' in error and sheet.writes == []


@pytest.mark.parametrize('broken', ['fields=sheets.properties', 'Settings!A:B'])
def test_unreadable_setting_writes_nothing(connect, broken):
    sheet = connect(_years())
    sheet.fail = broken
    assert gs.sync_inspection_row(_inspection())[0] is False
    assert gs.write_invoice_paid(_inspection(), True)[0] is False
    assert gs.delete_inspection_row(_inspection())[0] is False
    assert sheet.writes == []


# ── One tab per year ────────────────────────────────────────────────────────

@pytest.mark.parametrize('when, tab', [
    (datetime(2025, 12, 31), '2025'), (datetime(2026, 1, 1), '2026'), (datetime(2027, 3, 1), '2027'),
    (datetime(2029, 3, 1), '2027'), (datetime(2024, 3, 1), '2025'),
])
def test_new_job_goes_to_its_year(connect, when, tab):
    sheet = connect(_years(rows_2026=[_row('A1', '01/05/2026')]))
    assert gs.sync_inspection_row(_inspection(when=when)) == (True, None)
    assert sheet.rows(tab)[-1][3] == 'INS-7' and sheet.rows(tab)[-1][10] == '7'
    assert sum(len(sheet.rows(t)) for t in ('2025', '2026', '2027')) == 2
    assert sheet.rows('Dashboard') == []


def test_update_in_place_keeps_other_columns(connect):
    existing = _row('INS-7', '19/11/2026', 7, fee=95, paid=True, flags=['sent', 'pre', 'YES'])
    sheet = connect(_years(rows_2026=[_row('A1', '01/05/2026'), existing]))
    assert gs.sync_inspection_row(_inspection())[0]
    row = sheet.rows('2026')[1]
    assert len(sheet.rows('2026')) == 2 and row[2] == '20/11/2026'
    assert row[7] == 95 and row[9] is True and row[23:26] == ['sent', 'pre', 'YES']


def test_moving_to_another_year_takes_the_whole_row(connect):
    existing = _row('INS-7', '20/11/2026', 7, fee=95, paid=True, flags=['sent', 'pre', 'YES'])
    sheet = connect(_years(rows_2026=[_row('A1', '01/05/2026'), existing, _row('A2', '02/12/2026')],
                           rows_2027=[_row('B1', '04/01/2027')]))
    assert gs.sync_inspection_row(_inspection(when=datetime(2027, 1, 8)))[0]
    assert [r[3] for r in sheet.rows('2026')] == ['A1', 'A2']
    assert [r[3] for r in sheet.rows('2027')] == ['B1', 'INS-7']
    moved = sheet.rows('2027')[1]
    assert moved[2] == '08/01/2027' and moved[7] == 95 and moved[23:26] == ['sent', 'pre', 'YES']
    moves = [w for w in sheet.writes if w[1].endswith(':batchUpdate')]
    assert len(moves) == 1                                      # copy and remove happen together


def test_move_grows_a_full_tab(connect):
    sheet = connect(_years(rows_2026=[_row('INS-7', '20/11/2026', 7)],
                           rows_2027=[_row(f'B{i}', '04/01/2027') for i in range(49)]))
    assert gs.sync_inspection_row(_inspection(when=datetime(2027, 1, 8)))[0]
    assert sheet.rows('2027')[-1][3] == 'INS-7' and sheet.tab('2027')['rowCount'] == 51


def test_append_grows_a_full_tab(connect):
    sheet = connect(_years(rows_2027=[_row(f'B{i}', '04/01/2027') for i in range(49)]))
    assert gs.sync_inspection_row(_inspection(when=datetime(2027, 1, 8)))[0]
    assert sheet.rows('2027')[-1][3] == 'INS-7' and sheet.tab('2027')['rowCount'] == 51


@pytest.mark.parametrize('sheet', [_years(), FakeSheet([('2025', [])])], ids=['by-year', 'single-tab'])
def test_a_batch_reads_the_layout_once(connect, sheet):
    connect(sheet)
    layout, error = gs.get_sheet_layout()
    assert error is None
    sheet.reads.clear()
    for insp_id in (7, 8):
        job = _inspection(insp_id=insp_id, ref=f'INS-{insp_id}', when=datetime(2026, 11, insp_id))
        assert gs.sync_inspection_row(job, layout) == (True, None)
    assert len(sheet.reads) == 4                               # two per row, as before the split
    assert not any('Settings' in path or 'fields' in query for _, path, query in sheet.reads)


def test_failed_move_writes_nothing(connect):
    sheet = connect(_years(rows_2026=[_row('INS-7', '20/11/2026', 7)]))
    sheet.fail = ':batchUpdate'
    ok, error = gs.sync_inspection_row(_inspection(when=datetime(2027, 1, 8)))
    assert not ok and 'move' in error
    assert len(sheet.rows('2026')) == 1 and sheet.rows('2027') == []


def test_id_match_on_a_later_tab_beats_an_older_lookalike(connect):
    lookalike = _row('OLD', '20/11/2026')                       # same address, job and date, no ID
    sheet = connect(_years(rows_2025=[lookalike], rows_2026=[_row('INS-7', '20/11/2026', 7)]))
    assert gs.sync_inspection_row(_inspection())[0]
    assert sheet.rows('2025')[0][3] == 'OLD' and len(sheet.rows('2026')) == 1


def test_legacy_row_without_an_id_is_reused(connect):
    sheet = connect(_years(rows_2026=[_row('OLD', '20/11/2026')]))
    assert gs.sync_inspection_row(_inspection())[0]
    assert len(sheet.rows('2026')) == 1 and sheet.rows('2026')[0][10] == '7'


@pytest.mark.parametrize('paid', [True, False])
def test_paid_is_a_tick_box_value_found_by_id_first(connect, paid):
    sheet = connect(_years(rows_2025=[_row('INS-7', '01/05/2025', 99, paid=not paid)],   # duplicate reference
                           rows_2026=[_row('RENAMED', '20/11/2026', 7, paid=not paid)]))
    assert gs.write_invoice_paid(_inspection(), paid)[0]
    assert sheet.rows('2026')[0][9] is paid and sheet.rows('2025')[0][9] is (not paid)


def test_paid_falls_back_to_the_reference(connect):
    sheet = connect(_years(rows_2027=[_row('ins-7 ', '04/01/2027')]))
    assert gs.write_invoice_paid(_inspection(), True)[0] and sheet.rows('2027')[0][9] is True
    assert gs.write_invoice_paid(_inspection(ref='NOPE', insp_id=1), True)[0] is False


def test_delete_removes_from_whichever_year(connect):
    sheet = connect(_years(rows_2025=[_row('A1', '01/05/2025', 1)], rows_2027=[_row('INS-7', '04/01/2027', 7)]))
    assert gs.delete_inspection_row(_inspection())[0]
    assert sheet.rows('2027') == [] and len(sheet.rows('2025')) == 1


def test_force_sync_sees_references_in_every_year(connect):
    connect(_years([_row('A1', '01/05/2025')], [_row('B1', '01/05/2026')], [_row('C1', '04/01/2027')]))
    assert gs.get_existing_reference_numbers() == ({'a1', 'b1', 'c1'}, None)


def test_heads_up_and_pdf_imports_never_touch_the_sheet(connect):
    sheet = connect(_years())
    assert gs.sync_inspection_row(_inspection(kind='heads_up')) == (True, None)
    imported = _inspection()
    imported.pdf_import = True
    assert gs.sync_inspection_row(imported) == (True, None)
    assert sheet.writes == []
