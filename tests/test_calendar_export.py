"""Calendar format, schedule semantics and real HTTP/MCP interoperability."""
import json
import os
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

import calendar_export
import mercator
from support import HAVE_MCP, bridge_calls, dump, running_server
from test_publishing import Base
from unittest import skipUnless


class CalendarTests(Base):
    def scheduled(self, **extra):
        return self.call('post_upsert', platform='tiktok', title='Vídeo de prueba', status='scheduled',
                         scheduled_at='2026-10-25T02:30:00+02:00', **extra)['post']

    def export(self, **args):
        with mercator.reading() as conn:
            return calendar_export.export_calendar(conn, **args)

    def test_dates_offsets_and_no_invented_duration(self):
        for title, when in [('Antes', '2026-10-25T02:30:00+02:00'), ('Después', '2026-10-25T02:30:00+01:00'),
                            ('Sin zona', '2026-10-25T02:30:00'), ('Solo día', '2026-10-25')]:
            self.call('post_upsert', platform='x', title=title, status='scheduled', scheduled_at=when)
        text = self.export()['content']
        for value in ('DTSTART:20261025T003000Z', 'DTSTART:20261025T013000Z',
                      'DTSTART:20261025T023000\r\n', 'DTSTART;VALUE=DATE:20261025'):
            self.assertIn(value, text)
        self.assertNotIn('DTEND', text)
        self.assertNotIn('DURATION', text)
        self.assertNotIn('VALARM', text)

    def test_filters_statuses_and_read_only_stable_uid(self):
        post = self.scheduled(notes='Prueba de búsqueda')
        for status in ('idea', 'draft', 'published', 'archived'):
            self.call('post_upsert', platform='tiktok', title=status, status=status, scheduled_at='2026-10-25')
        with mercator.reading() as conn:
            before = '\n'.join(conn.iterdump())
        result = self.export(date_from='2026-10-25', date_to='2026-10-25', platform='tiktok', q='BÚSQUEDA')
        self.assertEqual(result['count'], 1)
        uid = next(line for line in result['content'].splitlines() if line.startswith('UID:'))
        self.call('post_upsert', post_id=post['id'], title='Título cambiado', scheduled_at='2026-10-26')
        self.assertIn(uid, self.export()['content'])
        self.assertEqual(self.export(date_to='2026-10-25')['count'], 0)
        self.assertEqual(self.export(platform='x')['count'], 0)
        with mercator.reading() as conn:
            after_change = '\n'.join(conn.iterdump())
        self.export()
        with mercator.reading() as conn:
            self.assertEqual(after_change, '\n'.join(conn.iterdump()))
        self.assertNotEqual(before, after_change)

    def test_escaping_utf8_and_folded_byte_length(self):
        self.scheduled(caption='Línea 1, café; \\ ruta\r\nBEGIN:VEVENT\n' + 'á🦋' * 80)
        text = self.export()['content']
        self.assertEqual(text.count('BEGIN:VEVENT\r\n'), 1)
        self.assertIn('Línea 1\\, café\\; \\\\ ruta\\nBEGIN:VEVENT\\n', text.replace('\r\n ', ''))
        self.assertTrue(text.endswith('END:VCALENDAR\r\n'))
        self.assertNotIn('\n', text.replace('\r\n', ''))
        self.assertTrue(all(len(line.encode('utf-8')) <= 75 for line in text.split('\r\n')))
        self.assertIn('á🦋' * 80, text.replace('\r\n ', ''))

    def test_export_has_no_list_pagination_cap(self):
        self.scheduled()
        with mercator.session() as conn:
            for _ in range(1001):
                conn.execute('INSERT INTO posts (platform,title,caption,hashtags,media_ref,status,scheduled_at,published_at,url,notes,external_id,created_at,updated_at) '
                             'SELECT platform,title,caption,hashtags,media_ref,status,scheduled_at,published_at,url,notes,external_id,created_at,updated_at FROM posts WHERE id=1')
        result = self.export()
        self.assertEqual(result['count'], 1002)
        self.assertEqual(result['content'].count('BEGIN:VEVENT'), 1002)
        self.assertEqual(len({line for line in result['content'].splitlines() if line.startswith('UID:')}), 1002)

    def test_invalid_filters_fail_honestly(self):
        for args in ({'date_from': '2026-02-30'}, {'date_to': 'mañana'}, {'date_from': '2026-10-01T12:00'},
                     {'date_from': '2026-10-02', 'date_to': '2026-10-01'}, {'date_from': None},
                     {'platform': 'invalid'}, {'q': 1}):
            with self.assertRaises(ValueError, msg=args):
                self.export(**args)

    def test_http_download_and_tool_link_are_complete(self):
        post = self.scheduled()
        with running_server() as port, patch.dict(os.environ, MERCATOR_PORT=str(port)):
            meta = self.call('posts_calendar_export', **{'from': '2026-10-25', 'q': 'Vídeo'})
            self.assertEqual(meta['count'], 1)
            self.assertNotIn('content', meta)
            with urlopen(meta['download_url']) as response:
                text = response.read().decode('utf-8')
                self.assertEqual(response.headers['X-Mercator-Events'], '1')
                self.assertEqual(response.headers.get_content_type(), 'text/calendar')
                self.assertIn('attachment;', response.headers['Content-Disposition'])
            self.assertIn(f'URL:http://127.0.0.1:{port}/publicacion#post-{post["id"]}', text)
            with self.assertRaises(HTTPError) as caught:
                urlopen(f'http://127.0.0.1:{port}/api/posts/calendar.ics?status=published')
            self.assertEqual(caught.exception.code, 400)

    @skipUnless(HAVE_MCP, 'mcp SDK unavailable')
    def test_real_stdio_mcp_download(self):
        self.scheduled()
        with running_server() as port, patch.dict(os.environ, MERCATOR_PORT=str(port)):
            results = bridge_calls(port, self.data, [('posts_calendar_export', {'platform': 'tiktok'})])
            self.assertIn('posts_calendar_export', [tool.name for tool in results['tools']])
            wire = dump(results['results'][0])
            self.assertFalse(wire.get('isError'))
            result = json.loads(next(item['text'] for item in wire['content'] if item['type'] == 'text'))
            with urlopen(result['download_url']) as response:
                self.assertEqual(response.read().count(b'BEGIN:VEVENT'), 1)
