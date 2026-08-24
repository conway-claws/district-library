---
title: CPS Live Feed, 2023-2024
org: conway-public-schools
unit:
type: feed
format: json
location: district-site
url: https://www.conwayschools.org/o/cps/live-feed
drive_id:
drive_kind:
rights: public-web
text: text/cpsd-cps-live-feed-2023-2024.md
retrieved: 2026-08-09
verified: 2026-08-24
status: current
tags: [live-feed, 2023-2024]
last_check: 2026-08-24
fail_since:
fail_reason:
---
Append-only capture of the school's live feed (official day-to-day
communications), maintained by bin/feed_watch.py from the open Thrillshare
API. Entries are newest-last, deduped by post id.

API anomaly, observed 2026-08-09: this section's endpoint returns HTTP 500 for
page_no=32 at every page size, and its page sizes disagree about total history
(per_page=25/50 enumerate to an end near post ~3,000; per_page=100 serves 459
further posts beyond it, captured here). Every reachable enumeration shows zero
uncaptured posts; weekly incremental runs never paginate deep enough to hit this.
