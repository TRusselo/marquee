# Implementation Guide: Emby backend & ESP32 target

> ### ⚠️ Test branch — nothing here is verified
>
> This document describes work in progress on `feature/emby-esp32-support`, a
> fork of [Jamisonfitz/marquee](https://github.com/Jamisonfitz/marquee). The
> Emby backend and the ESP32 display target are **new, unreleased, and have not
> been tested in a real deployment.** Code here is exercised only by
> `python cast/cast.py --selftest`.
>
> Read this as a description of intent, not a procedure known to work.

How the Emby media-source seam and the ESP32 display-target seam actually work
inside `cast/cast.py`, and how to extend either one. For the high-level picture
and diagrams, see `ARCHITECTURE_EMBY_ESP32.md` — this doc is the "how the seams
are wired in code" companion to it.

> Everything described here lives in the single file `cast/cast.py`. There is
> no separate module/abstraction layer — earlier drafts of these docs
> described one that was never built.

## The shape of the app

`cast/cast.py` is one Python 3.13 (stdlib-only) script that Docker runs
directly (`python cast/cast.py`). It's a push service built around one loop:

```
loop():
    every POLL_SECONDS (default 5):
        session = get_session()
        write output/now-playing.json (normalized dict)
        on play -> device_show(PAGE_URL)
        on stop -> device_hide()
```

It also runs a built-in HTTP server (`ThreadingHTTPServer` on `SERVE_PORT`,
default 8084) that serves the settings UI, the card page, and the read-only
`/api/now-playing.json` API — see `QUICK_REFERENCE.md` for the full route list.

## Seam 1: media backend (`MEDIA_BACKEND=plex|emby`)

The entry point is `get_session()`, which dispatches on `MEDIA_BACKEND`:

- `plex` (default) → `current_session()` → fetches Plex's `GET
  /status/sessions` (XML) and hands it to `parse_session()`.
- `emby` → `emby_current_session()` → fetches Emby's `GET
  /Sessions?api_key=...` (JSON) and hands it to `parse_emby_session()`.

Both parsers produce **the same normalized dict** — see "The now-playing.json
contract" below. Nothing downstream (the loop, the HTTP server, the card page,
an ESP32) ever branches on which backend is active; they only ever see the
normalized dict.

Emby-specific notes:
- Auth is a query-param `api_key`, not Plex's `X-Plex-Token` header.
- Duration is in ticks (÷ 10,000 = ms), where Plex is already ms.
- Genres/ratings come embedded in the `/Sessions` payload (Plex needs a
  second `/library/metadata` fetch).
- Emby has no RT *audience* score, only `CriticRating` (→ `rtCritic`).
  `CommunityRating` maps to `imdb`.

### Adding a third backend

1. Write a `<name>_current_session()` that talks to the new server and
   returns its raw session payload.
2. Write a `parse_<name>_session()` that maps that payload onto the same
   normalized dict keys everything else already consumes (see the contract
   below — copy `parse_emby_session()`'s shape, it's the newer of the two).
3. Add a branch in `get_session()` for the new `MEDIA_BACKEND` value.
4. Add whatever env vars the new backend needs (host/token/etc.) next to the
   existing `PLEX_*` / `EMBY_*` ones.

That's it — the loop, the HTTP server, the card page, and any ESP32/ESPHome
display keep working unmodified because they only depend on the normalized
dict, never on backend internals.

## Seam 2: device target (`CAST_TARGET=nest|esp32`)

Four functions form the seam, each dispatching on `CAST_TARGET`:

- `device_show(page_url)` — start displaying.
  - `nest`: `nest_show` runs `catt cast_site <PAGE_URL>` (DashCast loads the
    card page in the Hub's browser).
  - `esp32`: `esp32_show` does `POST http://ESP32_HOST:ESP32_PORT/display`
    with body `{"json_url": "http://<marquee>/now-playing.json"}`.
- `device_hide()` — stop displaying.
  - `nest`: `nest_hide` runs `catt stop`.
  - `esp32`: `esp32_hide` does `POST /stop`.
- `device_available()` — is a target configured/reachable.
  - `nest`: checks `hub_ip()` is set.
  - `esp32`: `GET /status` reachable.
- `device_active()` — is something currently showing.
  - `nest`: `dashcast_active()`.
  - `esp32`: `GET /status` → `displaying` flag.

Why the two targets look different: a Nest/Cast device runs a browser, so
Marquee just tells it (push) to load the card URL, and the browser itself
polls the JSON for live progress. A bare ESP32 can't run a browser, so Marquee
only pushes the show/hide *lifecycle*; the device itself *pulls*
`now-playing.json` to render the card natively (see `esp32/marquee_display.ino`,
reference firmware, hardware-unverified — board is on order).

### Adding a third device target

1. Write `<name>_show(page_url)` / `<name>_hide()` that do whatever's needed
   to start/stop the display.
2. Write `<name>_available()` / `<name>_active()` if the target can report
   those (used for settings-UI status and idempotency).
3. Add a branch in `device_show()` / `device_hide()` / `device_available()` /
   `device_active()` for the new `CAST_TARGET` value.
4. Add whatever env vars the new target needs (host/port/etc.) next to the
   existing `HUB_IP` / `ESP32_HOST` / `ESP32_PORT` ones.

The device side never needs to know which media backend produced the data —
it only ever renders/pulls `now-playing.json`.

## The `now-playing.json` contract — the real extension point

Both seams meet at one normalized dict, written to `output/now-playing.json`
and served read-only at `/api/now-playing.json`. This is intentionally the
*only* thing a new backend has to produce and the *only* thing a new device
target has to consume — nothing else needs to change.

Keys: `playing` (bool), `type` (`movie`/`episode`), `key`, `title`, `year`,
`subtitle` (episodes: "S# · E# · Name"), `state` (`playing`/`paused`),
`progress` (`offsetMs`, `durationMs`), `runtime` (e.g. "1h 59m"), `summary`,
`contentRating`, `genres` (≤3), `media` (e.g. "1080p · H264 · EAC3"), `scores`
(`imdb`, `rtCritic`, `rtCriticFresh`, and Plex-only `rtAudience` /
`rtAudienceFresh`), `stinger` (`during`/`after`), and `poster`/`backdrop`/
`logo` booleans.

If idle, the API returns `{"playing": false}`.

## Guarding the unchanged path

Plex + Nest behavior is unchanged by any of this. Run
`python cast/cast.py --selftest` to sanity-check the parsing/URL-building
logic without a live server. Emby is unit/mock-verified but not yet verified
against a live Emby server; the ESP32 target and firmware are implemented but
hardware-unverified.

## See also

- `ARCHITECTURE_EMBY_ESP32.md` — design rationale and diagrams.
- `QUICK_REFERENCE.md` — env vars, routes, file layout cheat-sheet.
- `FEATURE_SUMMARY.md` — current implementation/verification status.
