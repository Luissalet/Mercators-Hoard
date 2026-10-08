import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import agent_tools
import crm
import mercator
import mercator_family
from support import HAVE_MCP, bridge_calls, dump, running_server


class CRMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for field, value in [('DATA', root), ('DB', root / 'mercator.sqlite3')]:
            p = patch.object(mercator, field, value); p.start(); self.addCleanup(p.stop)
        self.addCleanup(mercator.close_databases)
        self.company = agent_tools.call_tool('crm_company_save', {'name': 'Estudio', 'project': 'IA'})['company']

    def deal(self, **fields):
        return agent_tools.call_tool('crm_deal_save', {'company_id': self.company['id'], 'title': 'Asistente',
            'project': 'IA', 'amount': '120.10', 'probability': 25, **fields})['deal']

    def test_projects_can_share_company_and_filter_real_deals(self):
        ia = self.deal(); cad = self.deal(project='3D', title='Carcasa')
        result = agent_tools.call_tool('crm_list', {'project': '3D'})
        self.assertEqual([d['id'] for d in result['deals']], [cad['id']])
        self.assertEqual(result['companies'][0]['id'], self.company['id'])
        self.assertEqual(agent_tools.call_tool('crm_list', {'q': 'Estudio'})['deal_total'], 2)
        self.assertEqual(agent_tools.call_tool('crm_get', {'kind':'deal','id':ia['id']})['revision'], 1)

    def test_updates_require_revision_and_preserve_fields(self):
        deal = self.deal()
        with self.assertRaisesRegex(ValueError, 'recarga'):
            agent_tools.call_tool('crm_deal_save', {'id': deal['id'], 'stage':'won'})
        saved = agent_tools.call_tool('crm_deal_save', {'id': deal['id'], 'expected_revision':1, 'stage':'won'})['deal']
        self.assertEqual((saved['title'], saved['revision'], saved['amount']), ('Asistente', 2, '120.10'))
        with self.assertRaisesRegex(ValueError, 'recarga'):
            agent_tools.call_tool('crm_deal_save', {'id': deal['id'], 'expected_revision':1, 'stage':'lost'})
        self.assertEqual(len(saved['activities']), 2)

    def test_concurrent_edit_has_one_winner(self):
        deal = self.deal()
        def write(stage):
            try:
                return agent_tools.call_tool('crm_deal_save', {'id': deal['id'], 'expected_revision':1, 'stage':stage})['deal']['stage']
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(write, ['won','lost']))
        self.assertEqual(outcomes.count('conflict'), 1)

    def test_decimal_summary_keeps_currencies_and_won_out_of_sales(self):
        self.deal(); self.deal(currency='USD', amount='80.00', probability=50)
        self.deal(stage='won', amount='30.00'); self.deal(stage='lost', amount='999.00')
        summary = agent_tools.call_tool('crm_summary', {})
        self.assertEqual(summary['currencies']['EUR'], {'open':'120.10','weighted':'30.03','won':'30.00'})
        self.assertEqual(summary['currencies']['USD']['weighted'], '40.00')
        with mercator.reading() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sales').fetchone()[0], 0)

    def test_activity_is_real_idempotent_and_conflicting_request_rejected(self):
        deal = self.deal()
        args = {'deal_id':deal['id'], 'note':'Reunión: propuesta pendiente', 'request_id':'meeting-1', 'source_ref':'hoard://funes/meeting/4'}
        one = agent_tools.call_tool('crm_activity_add', args)
        self.assertEqual(one, agent_tools.call_tool('crm_activity_add', args))
        with self.assertRaisesRegex(ValueError, 'otra actividad'):
            agent_tools.call_tool('crm_activity_add', {**args, 'note':'Otra nota'})
        with self.assertRaisesRegex(ValueError, 'zona horaria'):
            agent_tools.call_tool('crm_activity_add', {**args, 'request_id':'bad', 'observed_at':'2026-10-05'})

    def test_references_and_invalid_values_fail_without_partial_write(self):
        invalid = [{'amount':'NaN'}, {'amount':'-1'}, {'amount':'1.999'}, {'probability':True}, {'probability':101},
                   {'currency':'eur'}, {'stage':'fake'}, {'due_on':'2026-02-30'}, {'people_ref':'hoard://kafka/doc/1'},
                   {'document_refs':['hoard://people/person/1']}, {'document_refs':[None]}, {'company_id':'a'*32}]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.deal(**fields)
        self.assertEqual(agent_tools.call_tool('crm_list', {})['deal_total'], 0)

    def test_export_round_trips_text_history_and_neutralizes_csv_formulas(self):
        deal = self.deal(title='=WEBSERVICE("bad")', notes='ñ,\n"cita"', document_refs=['hoard://atlas/file/7'])
        agent_tools.call_tool('crm_activity_add', {'deal_id':deal['id'], 'note':'Llamada confirmada', 'request_id':'call'})
        exported = agent_tools.call_tool('crm_export', {'project':'IA'}, cap=False)
        self.assertIn("'=WEBSERVICE", exported['csv'])
        self.assertEqual(json.loads(json.dumps(exported))['deals'][0]['notes'], 'ñ,\n"cita"')
        self.assertEqual(len(exported['activities']), 2)

    def test_followup_agenda_uses_contract_dates_and_excludes_closed(self):
        deal = self.deal(due_on='2026-10-08', next_action='Revisar propuesta')
        with mercator.reading() as conn:
            items = crm.agenda_items(conn, date(2026,10,5), date(2026,10,10), 'http://127.0.0.1:5195')
        self.assertEqual(items[0]['start'], '2026-10-08')
        answer = mercator_family.agenda(mercator.agenda_provider,'2026-10-05','2026-10-10','work')
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(answer['items'][0]['kind'], 'followup')
        agent_tools.call_tool('crm_deal_save', {'id':deal['id'],'expected_revision':1,'stage':'won'})
        self.assertEqual(mercator_family.agenda(mercator.agenda_provider,'2026-10-05','2026-10-10','')['items'], [])

    def test_database_reopen_preserves_pipeline(self):
        deal = self.deal()
        mercator.close_databases()
        self.assertEqual(agent_tools.call_tool('crm_get', {'kind':'deal','id':deal['id']})['title'], 'Asistente')

    def test_migration_preserves_previous_sales_and_publications(self):
        from hoard_link.sqlkit import Database
        import publishing
        legacy_path = Path(self.temp.name) / 'legacy.sqlite3'
        old = Database(legacy_path, migrations=mercator.MIGRATIONS[:2])
        with old.tx() as conn:
            conn.execute("INSERT INTO sales(fingerprint,sold_at,product,amount,currency) VALUES ('old','2026-09-01','Modelo','17.50','EUR')")
            publishing.upsert_post(conn, {'title':'Publicación previa','platform':'x'})
        self.assertEqual(old.schema_version, 2)
        old.close()
        with patch.object(mercator, 'DB', legacy_path):
            self.assertEqual(mercator.database().schema_version, 3)
            with mercator.reading() as conn:
                self.assertEqual(conn.execute('SELECT amount FROM sales').fetchone()['amount'],'17.50')
                self.assertEqual(conn.execute('SELECT title FROM posts').fetchone()['title'],'Publicación previa')
            self.assertEqual(agent_tools.call_tool('crm_list', {})['deal_total'], 0)

    def test_pagination_unknown_arguments_and_catalog_annotations(self):
        for number in range(3): self.deal(title=str(number))
        page = agent_tools.call_tool('crm_list', {'limit':1,'offset':1})
        self.assertEqual((len(page['deals']),page['deal_total']), (1,3))
        with self.assertRaises(ValueError): agent_tools.call_tool('crm_list', {'limit':0})
        with self.assertRaises(ValueError): agent_tools.call_tool('crm_company_save', {'name':'X','token':'secret'})
        catalog = {t['name']:t for t in agent_tools.tool_catalog()}
        self.assertFalse(catalog['crm_deal_save']['annotations']['readOnlyHint'])
        self.assertTrue(catalog['crm_activity_add']['annotations']['idempotentHint'])

    def test_http_writes_are_guarded_and_visible_to_agent_contract(self):
        with running_server() as port:
            with closing(HTTPConnection('127.0.0.1', port)) as conn:
                payload=json.dumps({'name':'Desde interfaz','project':'3D'})
                conn.request('POST','/api/crm/company',payload,{'Content-Type':'application/json','Origin':'https://foreign.example'})
                r=conn.getresponse();r.read();self.assertEqual(r.status,403)
                conn.request('POST','/api/crm/company',payload,{'Content-Type':'application/json'})
                r=conn.getresponse();data=json.loads(r.read());self.assertEqual(r.status,200)
                conn.request('GET','/api/crm?project=3D');r=conn.getresponse();listing=json.loads(r.read())
                self.assertEqual(listing['companies'][0]['id'],data['company']['id'])
                conn.request('GET','/api/agent/tools');r=conn.getresponse();catalog=json.loads(r.read())
                self.assertIn('crm_deal_save',{t['name'] for t in catalog['tools']})

    def test_http_database_failure_answers_with_recoverable_error(self):
        with running_server() as port, closing(HTTPConnection('127.0.0.1',port)) as conn:
            with patch.object(agent_tools,'call_tool',side_effect=sqlite3.OperationalError('disk failure')):
                conn.request('POST','/api/crm/company',json.dumps({'name':'X'}),{'Content-Type':'application/json'})
                response=conn.getresponse();body=json.loads(response.read())
                self.assertEqual(response.status,500)
                self.assertIn('Reintenta',body['error'])

    @unittest.skipUnless(HAVE_MCP, 'MCP package required')
    def test_real_stdio_bridge_reads_saved_pipeline(self):
        deal=self.deal()
        with running_server() as port:
            mercator_family.configure(mercator.DATA)
            answer=bridge_calls(port,mercator.DATA,[('crm_get',{'kind':'deal','id':deal['id']})])
        wire=dump(answer['results'][0])
        self.assertFalse(wire.get('isError'))
        self.assertIn('Asistente', json.dumps(wire,ensure_ascii=False))
