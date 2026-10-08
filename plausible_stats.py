"""Plausible v2 statistics with query provenance; no event collection or invented numbers."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

METRICS = {'visitors','visits','pageviews','views_per_visit','bounce_rate','visit_duration','events','scroll_depth','percentage','conversion_rate','group_conversion_rate','average_revenue','total_revenue','time_on_page'}
PERIODS = {'day','24h','7d','28d','30d','91d','month','6mo','12mo','year','all'}

def dimension(value):
    return isinstance(value,str) and bool(re.fullmatch(r'(?:event|visit|time):[a-z_]+|time|event:props:[\w.-]{1,100}',value))

def validate_filter(value,depth=0):
    if depth>6 or not isinstance(value,list) or not 2<=len(value)<=4:raise ValueError('Invalid or over-nested filter')
    op=value[0]
    if op in ('and','or'):
        if len(value)!=2 or not isinstance(value[1],list) or not 1<=len(value[1])<=50:raise ValueError('Invalid logical filter')
        for child in value[1]:validate_filter(child,depth+1)
    elif op=='not':
        if len(value)!=2:raise ValueError('Invalid not filter')
        validate_filter(value[1],depth+1)
    else:
        if op not in ('is','is_not','contains','contains_not','matches','matches_not') or len(value)<3 or not (dimension(value[1]) or value[1]=='segment') or value[1].startswith('time'):raise ValueError('Unsupported simple filter')
        if value[1]=='event:goal' and op not in ('is','contains'):raise ValueError('Goals support is/contains filters')
        if not isinstance(value[2],list) or not 1<=len(value[2])<=100 or any(not isinstance(v,(str,int)) or isinstance(v,bool) or len(str(v))>1000 for v in value[2]):raise ValueError('Invalid filter clauses')
        if len(value)==4 and (op not in ('is','contains') or not isinstance(value[3],dict) or set(value[3])!={'case_sensitive'} or not isinstance(value[3]['case_sensitive'],bool)):raise ValueError('Invalid filter modifiers')

def query_body(args):
    site = args.get('site_id')
    if not isinstance(site, str) or not 1 <= len(site) <= 255 or re.search(r'[\s/]', site):
        raise ValueError('site_id must be the site domain registered in Plausible')
    period = args.get('date_range', '30d')
    if isinstance(period, list):
        if len(period) != 2:
            raise ValueError('date_range requires start and end')
        start, end = [datetime.fromisoformat(v) for v in period]
        if start.tzinfo != end.tzinfo and (start.tzinfo is None or end.tzinfo is None):
            raise ValueError('Both dates must use consistent timezone awareness')
        if start > end:
            raise ValueError('Start must precede end')
    elif not isinstance(period, str) or period not in PERIODS:
        raise ValueError('Unsupported date_range')
    metrics = args.get('metrics') or ['visitors','pageviews']
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 14 or any(v not in METRICS for v in metrics) or len(set(metrics)) != len(metrics):
        raise ValueError('Select distinct supported Plausible metrics')
    dimensions = args.get('dimensions') or []
    if not isinstance(dimensions, list) or len(dimensions) > 4 or any(not dimension(v) for v in dimensions):
        raise ValueError('Invalid Plausible dimensions')
    filters=args.get('filters',[])
    if not isinstance(filters,list) or len(filters)>50 or len(json.dumps(filters))>20000:raise ValueError('Invalid or oversized filters')
    for value in filters:validate_filter(value)
    limit=args.get('page_size',1000);offset=args.get('offset',0)
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=1000 or isinstance(offset,bool) or not isinstance(offset,int) or not 0<=offset<=1000000:raise ValueError('Invalid pagination')
    ordering=args.get('order_by',[])
    if not isinstance(ordering,list) or len(ordering)>8 or any(not isinstance(v,list) or len(v)!=2 or v[0] not in metrics+dimensions or v[1] not in ('asc','desc') for v in ordering):raise ValueError('Invalid order_by')
    return {'site_id':site,'date_range':period,'metrics':metrics,'dimensions':dimensions,'filters':filters,'order_by':ordering,'pagination':{'limit':limit,'offset':offset}}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Plausible redirected; configure its final origin explicitly')

def fetch(body):
    origin = os.environ.get('PLAUSIBLE_URL','https://plausible.io').rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('PLAUSIBLE_URL must be a server origin')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Use HTTPS for a remote Plausible server')
    token = os.environ.get('PLAUSIBLE_API_KEY','').strip()
    if not token:
        raise ValueError('Configure PLAUSIBLE_API_KEY in the service environment')
    request = urllib.request.Request(origin+'/api/v2/query', data=json.dumps(body).encode(), headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}, method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=25) as response:
            raw = response.read(2*1024*1024+1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Plausible rejected the query (HTTP {exc.code})') from None
    except urllib.error.URLError:
        raise ValueError('Plausible is unreachable; no statistics were stored') from None
    if len(raw) > 2*1024*1024:
        raise ValueError('Plausible response exceeds 2 MiB')
    return json.loads(raw), origin

def ensure(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS plausible_snapshots (id TEXT PRIMARY KEY,project TEXT,observed_at TEXT,origin TEXT,query TEXT,response TEXT)')

def capture(conn, project, body, response, origin):
    if not isinstance(project,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',project):
        raise ValueError('project must be a short stable identifier')
    if not isinstance(response,dict) or not isinstance(response.get('results'),list) or len(response['results']) > 1000:
        raise ValueError('Malformed Plausible results')
    for row in response['results']:
        if not isinstance(row,dict) or not isinstance(row.get('metrics'),list) or len(row['metrics']) != len(body['metrics']) or not isinstance(row.get('dimensions'),list) or len(row['dimensions']) != len(body['dimensions']):
            raise ValueError('Plausible result does not match requested columns')
        if any(isinstance(v,(int,float)) and (isinstance(v,bool) or not math.isfinite(v)) for v in row['metrics']):
            raise ValueError('Invalid numeric result')
    query = json.dumps(body,sort_keys=True,ensure_ascii=False)
    values = json.dumps(response,sort_keys=True,ensure_ascii=False,allow_nan=False)
    id = hashlib.sha256((project+'\0'+origin+'\0'+query+'\0'+values).encode()).hexdigest()
    observed = datetime.now(timezone.utc).isoformat()
    ensure(conn)
    added = conn.execute('INSERT OR IGNORE INTO plausible_snapshots VALUES (?,?,?,?,?,?)',(id,project,observed,origin,query,values)).rowcount == 1
    row = conn.execute('SELECT observed_at FROM plausible_snapshots WHERE id=?',(id,)).fetchone()
    return {'ok':True,'id':id,'added':added,'project':project,'observed_at':row[0],'origin':origin,'query':body,'response':response}

def list_snapshots(conn, project='', limit=20):
    ensure(conn)
    rows = conn.execute('SELECT id,project,observed_at,origin,query,response FROM plausible_snapshots WHERE (?="" OR project=?) ORDER BY rowid DESC LIMIT ?',(project,project,max(1,min(100,int(limit))))).fetchall()
    return {'snapshots':[{'id':r[0],'project':r[1],'observed_at':r[2],'origin':r[3],'query':json.loads(r[4]),'response':json.loads(r[5])} for r in rows]}
