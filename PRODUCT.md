# Mercator's Hoard

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

This first version uses a Python standard library server with a small local
web interface. It can run without adding a large runtime to the account
monitoring tool. This is an implementation choice for Mercator, not a standing
preference for future Hoards.

## Users

The owner of the Hoard projects, checking the health and commercial progress of
active projects from their own computer.

## Product Purpose

See how WatchHoard and BookHoard evolve, including real user growth and Worker
traffic when authorized. Track products prepared for Cults and sales imported
from Cults. Compare current figures with recorded history and see when a source
last answered. Success means a number can be traced to its provider and date.

## Operating Context

WatchHoard and BookHoard deploy static web apps as Cloudflare Workers and use
separate Supabase projects. WatchHoard has a local server key; BookHoard's
checked-in app configuration has only a public key. Cults listings for the
owner's models live in folder-level `cults3d.json` files prepared by Vulcan.
Cults sales can be exported as CSV. This application runs on loopback and keeps
its snapshots locally.

## Capabilities and Constraints

- Read-only collection from Supabase Auth and Cloudflare Analytics when the
  corresponding keys are available. No public key is treated as admin access.
- Import Cults sales CSV without duplicating prior imports. Show revenue by
  product and month, separated by currency.
- Scan the existing model folders for product listing status; do not edit them.
- Every metric identifies its source, observation time and connection state.
- Never invent counts when an account is unconfigured or unavailable.
- Open decision: API access for BookHoard, Cloudflare and Cults sales has not
  been found in the local configuration yet.

## Evidence on Hand

- The two Worker names are `watchhoard` and `bookhoard` in their Wrangler files.
- A live Supabase Auth read returned 74 total WatchHoard users and 14 created
  in the previous 30 days on 2026-09-28. These are live figures, not fixtures.
- 724 model folders currently have a `cults3d.json` listing.
- No Cults sales CSV or Cults API credential has been found locally.

## Product Principles

1. A visible source and timestamp accompany each number.
2. An unavailable source stays visibly unavailable; old data is not presented
   as current.
3. Read product sources without modifying them.
4. Keep credentials out of the browser and source control.
