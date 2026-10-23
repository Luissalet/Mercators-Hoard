"""Read-only iCalendar export of the stored publishing schedule (RFC 5545)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

import publishing


def _text(value: str) -> str:
    return value.replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _fold(line: str) -> str:
    parts, current, size = [], '', 0
    for char in line:
        length = len(char.encode('utf-8'))
        if size + length > 75:
            parts.append(current)
            current, size = ' ', 1
        current += char
        size += length
    return '\r\n'.join([*parts, current])


def _day(value: str, field: str) -> str:
    if not isinstance(value, str) or (value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
        raise ValueError(f'{field} debe ser YYYY-MM-DD')
    if value:
        date.fromisoformat(value)
    return value


def export_calendar(conn, *, date_from: str = '', date_to: str = '', platform: str = '', q: str = '', base_url: str = '') -> dict:
    """Export every matching scheduled row, without the list API's pagination cap.

    Date bounds refer to the stored calendar day, just like the publishing UI.
    Offset timestamps become UTC. Naive timestamps remain floating wall times;
    a date without an hour remains an all-day event. No duration is invented.
    """
    lo, hi = _day(date_from, 'from'), _day(date_to, 'to')
    if lo and hi and lo > hi:
        raise ValueError('from no puede ser posterior a to')
    if not isinstance(platform, str) or (platform and platform not in publishing.PLATFORMS):
        raise ValueError('platform no válida')
    if not isinstance(q, str):
        raise ValueError('q debe ser texto')
    needle = q.strip().casefold()
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', "PRODID:-//Mercator's Hoard//Publishing//ES", 'CALSCALE:GREGORIAN']
    count = 0
    for row in conn.execute("SELECT * FROM posts WHERE status='scheduled' ORDER BY scheduled_at, id"):
        post = publishing._row_post(row)
        when = post['scheduled_at']
        if platform and post['platform'] != platform:
            continue
        if needle and needle not in ' '.join([post['title'], post['caption'], ' '.join(post['hashtags']), post['notes']]).casefold():
            continue
        if not when or (lo and when[:10] < lo) or (hi and when[:10] > hi):
            continue
        if len(when) == 10:
            start = 'DTSTART;VALUE=DATE:' + date.fromisoformat(when).strftime('%Y%m%d')
        else:
            moment = datetime.fromisoformat(when)
            if moment.tzinfo is not None:
                start = 'DTSTART:' + moment.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            else:
                start = 'DTSTART:' + moment.strftime('%Y%m%dT%H%M%S')
        stamp = datetime.fromisoformat(post['updated_at']).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        uid = uuid.uuid5(uuid.NAMESPACE_URL, post['ref'] + ':' + post['created_at'])
        title = post['title'] or post['caption'][:80] or f"#{post['id']}"
        description = '\n\n'.join(part for part in (post['text'], post['notes'], post['ref']) if part)
        lines.extend(['BEGIN:VEVENT', f'UID:{uid}@mercator.hoard', f'DTSTAMP:{stamp}', f'LAST-MODIFIED:{stamp}',
                      start, 'SUMMARY:' + _text(f"{title} ({post['platform_label']})"),
                      'DESCRIPTION:' + _text(description)])
        if base_url:
            lines.append(f"URL:{base_url.rstrip('/')}/publicacion#post-{post['id']}")
        lines.extend(['TRANSP:TRANSPARENT', 'END:VEVENT'])
        count += 1
    lines.append('END:VCALENDAR')
    return {'content': '\r\n'.join(_fold(line) for line in lines) + '\r\n', 'count': count,
            'filename': 'mercator-programadas.ics', 'filters': {'from': lo, 'to': hi, 'platform': platform, 'q': q}}
