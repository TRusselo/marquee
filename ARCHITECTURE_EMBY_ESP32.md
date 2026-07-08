# Architecture: Emby backend & ESP32 target

How Marquee supports **Plex or Emby** as the media source and **Google Cast or
ESP32** as the display, without changing its original design.

> This document describes what the code actually does. An earlier draft referred
> to `media_backends.py`, `device_targets.py`, and `marquee_service.py` — those
> modules never existed and are not part of Marquee. Everything lives in the
> single file `cast/cast.py`.

## Design in one line

Marquee is a **push** service: one loop polls the media server, writes a
normalized `now-playing.json`, and drives the display on play/stop transitions.
Emby and ESP32 are added as two small **seams** inside `cast/cast.py`, each
chosen by an environment variable, each defaulting to the original behavior.

```
      MEDIA_BACKEND=plex|emby                 CAST_TARGET=nest|esp32
              │                                        │
   ┌──────────▼──────────┐    now-playing.json  ┌──────▼───────────┐
   │ get_session()       │  ───────────────────►│ device_show/hide │
   │  plex: /status/     │      (contract)      │  nest : catt     │
   │        sessions XML │                      │  esp32: HTTP POST │
   │  emby: /Sessions    │  ──► /api/now-       │                  │
   │        JSON         │       playing.json ─►│  (ESP32/ESPHome  │
   └─────────────────────┘      (polled)        │   also PULL this)│
        loop(), HTTP server, settings UI, output/ — unchanged
```

## The contract: `now-playing.json`

The card page (`output/index.html`), the read-only API, and any ESP32/ESPHome
display consume **only** this normalized dict — never Plex or Emby directly. So
"add a backend" means "produce this same dict from a new source."

Keys: `playing`, `type` (`movie`/`episode`), `key`, `title`, `year`,
`subtitle` (episodes), `state` (`playing`/`paused`), `progress`
(`offsetMs`/`durationMs`), `runtime`, `summary`, `contentRating`, `genres` (≤3),
`media` (e.g. `1080p · H264 · EAC3`), `scores`
(`imdb`, `rtCritic`, `rtCriticFresh`; Plex also has `rtAudience`/`rtAudienceFresh`),
`stinger`, and `poster`/`backdrop`/`logo` booleans.

## Backend seam (`MEDIA_BACKEND=plex|emby`)

`get_session()` dispatches to the selected backend; both return the contract dict:

| | Plex (default) | Emby |
|---|---|---|
| Session source | `GET /status/sessions` (XML) | `GET /Sessions?api_key=…` (JSON) |
| Entry point | `current_session()` | `emby_current_session()` |
| Parser | `parse_session()` | `parse_emby_session()` |
| Auth | `X-Plex-Token` | `api_key` (query param) |
| Genres/ratings | second `/library/metadata` fetch | embedded in `/Sessions` (enrichment fallback if absent) |
| Art | `/photo/:/transcode` | `/Items/{Id}/Images/…` (server resizes) |
| Duration | ms | ticks (÷10 000 = ms) |

**Emby fidelity notes:** Emby exposes an RT *critic* score (`CriticRating`) but no
RT *audience* score, so those two keys are omitted. `CommunityRating` maps to the
`imdb` number. Credits-scene (`stinger`) detection is backend-agnostic — it uses
the TMDb id from either backend when `TMDB_API_KEY` is set.

## Device seam (`CAST_TARGET=nest|esp32`)

`device_show(page_url)` / `device_hide()` / `device_available()` /
`device_active()` dispatch to the selected target:

| | Nest / Cast (default) | ESP32 |
|---|---|---|
| Show | `catt cast_site <PAGE_URL>` (DashCast) | `POST /display {"json_url": …}` |
| Hide | `catt stop` | `POST /stop` |
| Availability | `hub_ip()` set | `GET /status` reachable |
| Active? | `dashcast_active()` | `GET /status` → `displaying` |
| Renders by | loading the HTML card in the device's browser | pulling the JSON and drawing natively |

**Why the asymmetry:** a Cast device runs a browser, so Marquee just tells it to
load the card URL. A bare ESP32 can't run a browser, so Marquee pushes only the
**lifecycle** (show/hide) and the device **pulls** `now-playing.json` to render —
exactly how the Cast path already works, where the browser polls the JSON for
live progress.

## The read-only API

- `GET /api/now-playing.json` — the live contract dict (or `{"playing": false}`
  when idle), **CORS-enabled** for ESP32/ESPHome/Home Assistant. Also reachable
  as `/now-playing.json`.
- `GET /api/healthz` — `{ok, version}`.

## Two ways to build an ESP32 display

1. **ESPHome (recommended DIY path):** the device polls `/api/now-playing.json`
   and renders/switches pages itself. Marquee needs no per-device config. See the
   `docs/ESPHOME/` guides. (Use the `http_request` GET action + a JSON-parsing
   lambda — not a `text_sensor`, which truncates at ~255 bytes.)
2. **Custom firmware:** `esp32/marquee_display.ino` — a reference sketch
   (ArduinoJson 7 + ESP32 core 3.x) that implements the `POST /display`,
   `POST /stop`, `GET /status` contract above. Reference only; hardware-unverified.

Both consume the same JSON; pick per taste.

## What changed vs. the original app

Only additive seams and the API routes. Plex + Nest behavior is unchanged and is
guarded by `python cast/cast.py --selftest`. No files were split out; the app is
still one `cast/cast.py`.
