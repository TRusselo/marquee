# Quick Reference: Emby + ESP32 Support

> ### ⚠️ Test branch — nothing here is verified
>
> This document describes work in progress on `feature/emby-esp32-support`, a
> fork of [Jamisonfitz/marquee](https://github.com/Jamisonfitz/marquee). The
> Emby backend and the ESP32 display target are **new, unreleased, and have not
> been tested in a real deployment.** Code here is exercised only by
> `python cast/cast.py --selftest`.
>
> Read this as a description of intent, not a procedure known to work.

Fast lookup for env vars, routes, and file layout. Everything here is
implemented in the single file `cast/cast.py` — there is no separate module
tree.

## File layout

```
cast/cast.py          # the whole app: loop, HTTP server, both backends, both device targets
cast/settings.html     # settings UI template served at / and /settings
esp32/marquee_display.ino   # reference ESP32 firmware (hardware-unverified)
output/                # generated: now-playing.json, index.html (the card), static assets
docs/ESPHOME/          # ESPHome-based DIY display guides (alternative to the .ino)
ARCHITECTURE_EMBY_ESP32.md  # design/rationale
IMPLEMENTATION_GUIDE.md     # how the seams are wired, how to extend them
```

## Environment variables

| Var | Purpose | Default |
|---|---|---|
| `MEDIA_BACKEND` | `plex` or `emby` | `plex` |
| `PLEX_HOST` | Plex server URL | — |
| `PLEX_TOKEN` | Plex auth token | — |
| `EMBY_HOST` | Emby server URL | — |
| `EMBY_API_KEY` | Emby API key | — |
| `MEDIA_USERS` | Limit to specific user(s) (falls back to `PLEX_USERS` if unset) | — |
| `CAST_TARGET` | `nest` or `esp32` | `nest` |
| `HUB_IP` | Nest/Cast device IP | — |
| `ESP32_HOST` | ESP32 display IP/host | — |
| `ESP32_PORT` | ESP32 display port | `80` |
| `PAGE_URL` | Card page URL to cast (Nest target) | — |
| `TMDB_API_KEY` | Enables credits-scene (`stinger`) detection | — |
| `POLL_SECONDS` | Loop interval | `5` |
| `SERVE_PORT` | Built-in HTTP server port | `8084` |
| `REPO_DIR` | App/repo root inside container | `/app` |
| `DATA_DIR` | Persistent data/config dir | `/config` |

## Switching backend / target

```bash
# Emby instead of Plex
MEDIA_BACKEND=emby EMBY_HOST=http://emby.local:8096 EMBY_API_KEY=xxxx ...

# ESP32 instead of a Nest Hub
CAST_TARGET=esp32 ESP32_HOST=192.168.1.50 ESP32_PORT=80 ...
```

Both switches are independent — e.g. `MEDIA_BACKEND=emby` + `CAST_TARGET=esp32`
works the same as any other combination, since both seams only communicate
through the normalized `now-playing.json` dict.

## HTTP routes (built-in server, `SERVE_PORT`, default 8084)

| Route | Purpose |
|---|---|
| `/` , `/settings` | Settings UI (`cast/settings.html`) |
| `/image` | The card page (`output/index.html`) |
| `/settings.json` | Current settings as JSON |
| `/devices` | Device listing |
| `/healthz` | Basic health check |
| `/api/now-playing.json` (also `/now-playing.json`) | Read-only, CORS-enabled card state. `{"playing": false}` when idle. This is what an ESP32/ESPHome display polls. |
| `/api/healthz` | `{ok, version}`, CORS-enabled |
| `/release-notes` | Renders `CHANGELOG.md` |
| static files | Served from `output/` by basename |

## Sanity-checking without a live server

```bash
python cast/cast.py --selftest
```

Runs the parsing/URL-building self-checks (Plex + Emby parsing, ESP32 JSON-URL
derivation, etc.) without needing a reachable Plex/Emby/ESP32.

## now-playing.json — the normalized contract

Both backends produce the same dict; both device targets (and any ESP32/ESPHome
display) only ever consume it:

`playing`, `type` (`movie`/`episode`), `key`, `title`, `year`, `subtitle`
(episodes), `state` (`playing`/`paused`), `progress` (`offsetMs`/`durationMs`),
`runtime`, `summary`, `contentRating`, `genres` (≤3), `media`, `scores`
(`imdb`, `rtCritic`, `rtCriticFresh`, + Plex-only `rtAudience`/
`rtAudienceFresh`), `stinger` (`during`/`after`), `poster`/`backdrop`/`logo`
(bool).

## Status at a glance

- Plex + Nest: unchanged, existing behavior, guarded by `--selftest`.
- Emby backend: implemented, unit/mock-verified; live verification against a
  real Emby server still pending.
- ESP32 target + reference firmware (`esp32/marquee_display.ino`):
  implemented, hardware-unverified (board on order).

See `FEATURE_SUMMARY.md` for the full status writeup and
`ARCHITECTURE_EMBY_ESP32.md` / `IMPLEMENTATION_GUIDE.md` for design details.
