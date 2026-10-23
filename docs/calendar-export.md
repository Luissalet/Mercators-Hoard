# Publishing calendar export

In **Publication → Calendar**, **Descargar programadas (.ics)** downloads the
scheduled publications in the visible date cells, narrowed by the current
platform and text filters. Month view includes the adjacent days shown in its
six-week grid; week view exports its seven days. Drafts, ideas, archived and
published posts are excluded even when they retain a scheduled date.

The file includes titles, platform names, captions/hashtags, notes and a link
back to each Mercator post. Import it into a calendar application. This is a
copy of the current plan, without a subscription, automatic updates, social
publishing or changes to Mercator's records. Calendar applications decide how
to handle a later import of the same stable event UID.

## Dates

- A date without an hour becomes an all-day event.
- A timestamp with an explicit UTC offset becomes UTC, preserving the instant,
  including either side of a daylight-saving transition.
- A timestamp without a zone remains a floating wall time: the receiving
  calendar uses that hour locally. Mercator does not infer a timezone.
- No duration, attendee, reminder or busy-time reservation is added.

## Native API and MCP

`GET /api/posts/calendar.ics?from=2026-10-01&to=2026-10-31&platform=tiktok&q=video`
returns UTF-8 `text/calendar`, a download filename and `X-Mercator-Events`.
All filters are optional. `from` and `to` must be inclusive dates in
`YYYY-MM-DD`, compared with the stored calendar day, as in the UI.

`posts_calendar_export {from?, to?, platform?, q?}` is read-only. It returns
the event count, filters and local `download_url`. Open that URL while
Mercator is running to retrieve the complete file. The URL recalculates the
current plan when read; it is not a saved immutable artifact. It avoids the
assistant's 20,000-byte result cap and the list API's 1,000-row limit.

The native exporter uses the standard library. Its format follows
[RFC 5545](https://www.rfc-editor.org/rfc/rfc5545): CRLF, escaped text, physical
lines folded at 75 UTF-8 bytes, stable UIDs and modification timestamps.
[icalendar](https://github.com/collective/icalendar) provides an independent
parser for interoperability checks;
[ical-generator](https://github.com/sebbo2002/ical-generator) was examined as
an alternative generator. Neither library is a runtime dependency, and no
upstream source was copied.
