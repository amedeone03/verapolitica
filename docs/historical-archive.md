# Historical archive

The "Archivio" section covers the Republic from the Constituent Assembly (1946)
to today. Everything shown comes from official sources; gaps are shown as gaps.

## Legislatures

`legislatures` holds the Constituent Assembly (number 0) and every republic
legislature with start and end dates. The Alembic revision `a4d8c1e7f310`
seeds it from `data/fixtures/archive/legislatures.json`; SQLite demos seed it at
start-up. The `camera-history` job replaces republic rows with the dates
published by `dati.camera.it`, and the fixture never overwrites collected rows.

"Prima" and "Seconda Repubblica" are a journalistic convention, not an
institutional category. The era is derived from the legislature number
(I–XI / XII onwards) and never stored; the public page says so.

## Parliamentary roster

`historical_parliament_mandates` stores one row per official mandate (Camera
mandate URI), including ended mandates. These are roster rows, not profiles:
they do not enter the profile review queue. A row links to a `Politician` only
when the Camera person number matches a reviewed Camera profile identifier, and
the public API shows the link only if that profile is published.

```bash
VERAPOLITICA_CAMERA_HISTORY_LEGISLATURES=1-19 python -m scripts.run_jobs camera-history
VERAPOLITICA_SENATO_HISTORY_LEGISLATURES=1 python -m scripts.run_jobs senato-history
```

The Camera collector stores every SPARQL response body in one raw document
(schema `verapolitica_camera_history_v1`). The Senate job uses
`verapolitica_senato_history_v1` and writes `chamber=senato` mandates only: it
does not invent legislature dates (those stay on the Camera/fixture table) and
does not create office-holder rows. Both crons default to blank, so production
does not backfill 1–19 until an operator opts in. The first live Senate run
should be checked on a single legislature.

## Territories

Provinces are derived from ISTAT municipality codes (`/archive/provinces`).
Region and province history pages list published office holders (regional
presidents, mayors) and referendums with sources. Regional and provincial
series are fragmented, so every page carries a coverage note. Since Law
56/2014 provincial presidents and councils are no longer directly elected.

## Draft city and region timelines

`data/fixtures/archive/timelines/` holds editorial drafts of election
chronologies (cities such as Verona, regions, and a national file). They come
from secondary sources (Tuttitalia, Wikipedia) and are labelled **bozza non
verificata**. They are never auto-published as official office holders.

`GET /archive/timelines` lists them; `GET /archive/timelines/{slug}` returns
the events. When an ISTAT comune or region with the same name exists, the
payload includes `municipality_id` / `region_id` so Archivio can open the live
scheda (Verona, Milano, …). A redazione member can propose an official URL
(Eligendo, Ministero, ente) for one event; a second person publishes it. The
JSON draft stays as written. Wikipedia and Tuttitalia are refused. A published
verification never creates a sindaco or a DAIT mandate.

## Public API

| Route | Content |
| --- | --- |
| `GET /archive/legislatures` | Legislatures grouped by era, with mandate counts |
| `GET /archive/legislatures/{n}` | Dates, previous/next, referendums, published proposals, and promulgated laws in the period |
| `GET /archive/parliamentarians` | Roster, filterable by `legislature`, `chamber`, `q` |
| `GET /archive/provinces` | Provinces, optionally by `region` |
| `GET /archive/provinces/{code}` | Province history |
| `GET /archive/regions/{id}` | Region history |
| `GET /archive/timelines` | Draft city/region/national chronologies |
| `GET /archive/timelines/{slug}` | One draft chronology (Verona, Veneto, Italia, …) |
