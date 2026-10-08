"""Local commercial pipeline. Original implementation informed by sales-crm's UI.

Estimated deal values are never posted to revenue or Ledger automatically.
Contacts/documents remain references to their owning Hoards.
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

STAGES = ('lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost', 'archived')
SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_companies (
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crm_deals (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES crm_companies(id),
 revision INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS crm_company_deals ON crm_deals(company_id);
CREATE TABLE IF NOT EXISTS crm_activities (
 id TEXT PRIMARY KEY, deal_id TEXT NOT NULL REFERENCES crm_deals(id),
 kind TEXT NOT NULL, note TEXT NOT NULL, source_ref TEXT NOT NULL,
 observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
 request_id TEXT UNIQUE, fingerprint TEXT);
CREATE INDEX IF NOT EXISTS crm_deal_activities ON crm_activities(deal_id, recorded_at);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def text(value, field, maximum=200, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f'{field}: texto válido requerido (máximo {maximum})')
    return value.strip()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('ID CRM no válido')
    return value


def reference(value, owners=None):
    value = text(value, 'referencia', 500)
    if value:
        match = re.fullmatch(r'hoard://([a-z0-9_-]+)/[^\s?#]+', value)
        if not match or (owners and match[1] not in owners):
            raise ValueError('Referencia Hoard no válida para este campo')
    return value


def amount(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,12}(\.\d{1,2})?', value):
        raise ValueError('amount: importe decimal positivo como texto, hasta dos decimales')
    try:
        return str(Decimal(value).quantize(Decimal('.01')))
    except InvalidOperation as exc:
        raise ValueError('Importe no válido') from exc


def get(conn, kind, id):
    if kind not in ('company', 'deal'):
        raise ValueError('kind debe ser company o deal')
    table = 'crm_companies' if kind == 'company' else 'crm_deals'
    row = conn.execute(f'SELECT * FROM {table} WHERE id=?', (identifier(id),)).fetchone()
    if row is None:
        raise ValueError('Registro CRM no encontrado')
    result = {**json.loads(row['body']), 'id': row['id'], 'revision': row['revision'],
              'created_at': row['created_at'], 'updated_at': row['updated_at'],
              'ref': f'hoard://mercator/crm/{kind}/{id}'}
    if kind == 'deal':
        result['company_name'] = get(conn, 'company', result['company_id'])['name']
        result['activities'] = [dict(r) for r in conn.execute(
            'SELECT id,kind,note,source_ref,observed_at,recorded_at FROM crm_activities WHERE deal_id=? ORDER BY recorded_at DESC LIMIT 200', (id,))]
    return result


def save(conn, kind, args):
    defaults = ({'name': '', 'project': '', 'owner': '', 'segment': '', 'people_ref': '', 'notes': '', 'source_ref': ''}
                if kind == 'company' else {'company_id': '', 'title': '', 'project': '', 'owner': '', 'stage': 'lead',
                'amount': '0.00', 'currency': 'EUR', 'probability': 0, 'next_action': '', 'due_on': '',
                'people_ref': '', 'document_refs': [], 'notes': '', 'source_ref': ''})
    unknown = set(args) - set(defaults) - {'id', 'expected_revision'}
    if unknown:
        raise ValueError('Campos desconocidos: ' + ', '.join(sorted(unknown)))
    id = identifier(args['id']) if args.get('id') else uuid.uuid4().hex
    table = 'crm_companies' if kind == 'company' else 'crm_deals'
    previous = conn.execute(f'SELECT * FROM {table} WHERE id=?', (id,)).fetchone()
    expected = args.get('expected_revision')
    if previous:
        if type(expected) is not int or expected != previous['revision']:
            raise ValueError('El registro ha cambiado; recarga antes de guardar')
        body = json.loads(previous['body'])
    else:
        if args.get('id') or expected is not None:
            raise ValueError('Registro CRM no encontrado; crea sin id')
        body = defaults.copy()
    body.update({k: v for k, v in args.items() if k in defaults})
    for key in ('project', 'owner', 'notes', 'source_ref'):
        body[key] = text(body[key], key, 8000 if key == 'notes' else 500 if key == 'source_ref' else 200)
    body['source_ref'] = reference(body['source_ref'])
    body['people_ref'] = reference(body['people_ref'], {'people'})
    if kind == 'company':
        body['name'] = text(body['name'], 'name', required=True)
        body['segment'] = text(body['segment'], 'segment')
    else:
        get(conn, 'company', body['company_id'])
        body['title'] = text(body['title'], 'title', required=True)
        if body['stage'] not in STAGES:
            raise ValueError('Etapa comercial no válida')
        body['amount'] = amount(body['amount'])
        if not isinstance(body['currency'], str) or not re.fullmatch('[A-Z]{3}', body['currency']):
            raise ValueError('currency: código de tres letras mayúsculas')
        if type(body['probability']) is not int or not 0 <= body['probability'] <= 100:
            raise ValueError('probability: entero entre 0 y 100, estimado por el propietario')
        body['next_action'] = text(body['next_action'], 'next_action', 1000)
        body['due_on'] = text(body['due_on'], 'due_on', 10)
        if body['due_on']:
            try:
                if date.fromisoformat(body['due_on']).isoformat() != body['due_on']:
                    raise ValueError()
            except ValueError as exc:
                raise ValueError('due_on: fecha YYYY-MM-DD requerida') from exc
        refs = body['document_refs']
        if not isinstance(refs, list) or len(refs) > 30:
            raise ValueError('document_refs: máximo 30 referencias')
        body['document_refs'] = list(dict.fromkeys(reference(v, {'atlas', 'kafka', 'platos'}) for v in refs))
        if '' in body['document_refs']:
            raise ValueError('Referencia documental vacía')
    ts = now()
    revision = previous['revision'] + 1 if previous else 1
    encoded = json.dumps(body, ensure_ascii=False)
    if kind == 'company':
        conn.execute('INSERT INTO crm_companies VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body,updated_at=excluded.updated_at',
                     (id, revision, encoded, previous['created_at'] if previous else ts, ts))
    else:
        conn.execute('INSERT INTO crm_deals VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET company_id=excluded.company_id,revision=excluded.revision,body=excluded.body,updated_at=excluded.updated_at',
                     (id, body['company_id'], revision, encoded, previous['created_at'] if previous else ts, ts))
        before = json.loads(previous['body']) if previous else {}
        changes = {k: {'before': before.get(k), 'after': v} for k, v in body.items() if before.get(k) != v}
        conn.execute('INSERT INTO crm_activities VALUES (?,?,?,?,?,?,?,?,?)',
                     (uuid.uuid4().hex, id, 'change', json.dumps(changes, ensure_ascii=False), '', ts, ts, None, None))
    return get(conn, kind, id)


def activity_add(conn, args):
    deal = get(conn, 'deal', args['deal_id'])
    note = text(args.get('note'), 'note', 8000, True)
    source = reference(args.get('source_ref', ''))
    observed = args.get('observed_at') or now()
    if not isinstance(observed, str):
        raise ValueError('observed_at: fecha ISO con zona horaria requerida')
    try:
        parsed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
    except ValueError as exc:
        raise ValueError('observed_at: fecha ISO con zona horaria requerida') from exc
    request_id = text(args.get('request_id'), 'request_id', 100, True)
    # No synthesized timestamp in the fingerprint: a retry without observed_at is identical.
    fingerprint = json.dumps([deal['id'], note, source, args.get('observed_at')], ensure_ascii=False)
    previous = conn.execute('SELECT * FROM crm_activities WHERE request_id=?', (request_id,)).fetchone()
    if previous:
        if previous['fingerprint'] != fingerprint:
            raise ValueError('request_id ya pertenece a otra actividad')
        return {k: previous[k] for k in ('id', 'deal_id', 'kind', 'note', 'source_ref', 'observed_at', 'recorded_at')}
    id = uuid.uuid4().hex
    conn.execute('INSERT INTO crm_activities VALUES (?,?,?,?,?,?,?,?,?)',
                 (id, deal['id'], 'note', note, source, observed, now(), request_id, fingerprint))
    return dict(conn.execute('SELECT id,deal_id,kind,note,source_ref,observed_at,recorded_at FROM crm_activities WHERE id=?', (id,)).fetchone())


def records(conn, args):
    filters = {key: text(args.get(key, ''), key, 200) for key in ('project', 'owner', 'q', 'stage', 'company_id')}
    if filters['stage'] and filters['stage'] not in STAGES:
        raise ValueError('Etapa comercial no válida')
    companies = {r['id']: {**json.loads(r['body']), 'id': r['id'], 'revision': r['revision'], 'created_at': r['created_at'], 'updated_at': r['updated_at'],
                 'ref': f"hoard://mercator/crm/company/{r['id']}"} for r in conn.execute('SELECT * FROM crm_companies ORDER BY updated_at DESC')}
    deals = []
    for r in conn.execute('SELECT * FROM crm_deals ORDER BY updated_at DESC'):
        body = {**json.loads(r['body']), 'id': r['id'], 'revision': r['revision'], 'created_at': r['created_at'], 'updated_at': r['updated_at'],
                'ref': f"hoard://mercator/crm/deal/{r['id']}"}
        body['company_name'] = companies[body['company_id']]['name']
        if all(not filters[k] or body[k] == filters[k] for k in ('project', 'owner', 'stage', 'company_id')) and (
            not filters['q'] or filters['q'].casefold() in (body['title'] + ' ' + body['company_name'] + ' ' + body['notes']).casefold()):
            deals.append(body)
    # A company shared across projects remains selectable when it has a matching deal.
    related = {d['company_id'] for d in deals}
    company_rows = [c for c in companies.values() if c['id'] in related or (
        not filters['stage'] and all(not filters[k] or c[k] == filters[k] for k in ('project', 'owner')) and
        (not filters['company_id'] or c['id'] == filters['company_id']) and
        (not filters['q'] or filters['q'].casefold() in (c['name'] + ' ' + c['notes']).casefold()))]
    return company_rows, deals


def listing(conn, args):
    try:
        limit, offset = int(args.get('limit', 100)), int(args.get('offset', 0))
    except (ValueError, TypeError) as exc:
        raise ValueError('Paginación no válida') from exc
    if not 1 <= limit <= 500 or not 0 <= offset <= 1000000:
        raise ValueError('limit 1–500; offset 0–1000000')
    companies, deals = records(conn, args)
    return {'companies': companies[offset:offset+limit], 'deals': deals[offset:offset+limit],
            'company_total': len(companies), 'deal_total': len(deals), 'limit': limit, 'offset': offset, 'stages': list(STAGES)}


def summary(conn, args):
    companies, deals = records(conn, args)
    currencies = {}
    for deal in deals:
        totals = currencies.setdefault(deal['currency'], {'open': Decimal(0), 'weighted': Decimal(0), 'won': Decimal(0)})
        value = Decimal(deal['amount'])
        if deal['stage'] not in ('won', 'lost', 'archived'):
            totals['open'] += value
            totals['weighted'] += value * Decimal(deal['probability']) / 100
        elif deal['stage'] == 'won':
            totals['won'] += value
    return {'company_count': len(companies), 'deal_count': len(deals),
            'stages': {stage: sum(d['stage'] == stage for d in deals) for stage in STAGES},
            'currencies': {c: {k: str(v.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) for k, v in values.items()} for c, values in currencies.items()},
            'note': 'Importes estimados; ganado no equivale a cobrado. Probabilidades introducidas por el propietario.'}


def export(conn, args):
    companies, deals = records(conn, args)
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    fields = ['id', 'company_name', 'title', 'project', 'owner', 'stage', 'amount', 'currency', 'probability', 'next_action', 'due_on', 'people_ref', 'source_ref']
    writer.writerow(fields)
    # Prevent spreadsheet formula execution in user-maintained text.
    def safe(value):
        value = str(value)
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    for deal in deals:
        writer.writerow([safe(deal[k]) for k in fields])
    ids = {d['id'] for d in deals}
    activities = [dict(r) for r in conn.execute('SELECT id,deal_id,kind,note,source_ref,observed_at,recorded_at FROM crm_activities ORDER BY recorded_at') if r['deal_id'] in ids]
    return {'schema': 1, 'exported_at': now(), 'filters': {k: args.get(k, '') for k in ('project','owner','stage','company_id','q')},
            'companies': companies, 'deals': deals, 'activities': activities, 'csv': out.getvalue(), 'summary': summary(conn, args)}


def agenda_items(conn, date_from, date_to, base_url):
    _, deals = records(conn, {})
    return [{'id': 'mercator:followup:' + d['id'], 'title': d['next_action'] or d['title'], 'start': d['due_on'],
             'url': base_url + '/#crm', 'detail': d['company_name'] + ' · ' + d['project'], 'kind': 'followup', 'sphere': 'work'}
            for d in deals if d['stage'] not in ('won', 'lost', 'archived') and d['due_on'] and
            (not date_from or date.fromisoformat(d['due_on']) >= date_from) and (not date_to or date.fromisoformat(d['due_on']) <= date_to)]
