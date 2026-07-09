# Marquee

[![Build](https://github.com/Jamisonfitz/marquee/actions/workflows/container.yml/badge.svg)](https://github.com/Jamisonfitz/marquee/actions/workflows/container.yml)
[![Top language](https://img.shields.io/github/languages/top/Jamisonfitz/marquee)](https://github.com/Jamisonfitz/marquee)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker Pulls](https://img.shields.io/docker/pulls/jamisonfitz/marquee?logo=docker)](https://hub.docker.com/r/jamisonfitz/marquee)
[![Docker Image Version](https://img.shields.io/docker/v/jamisonfitz/marquee?sort=semver&logo=docker)](https://hub.docker.com/r/jamisonfitz/marquee/tags)
[![License](https://img.shields.io/github/license/Jamisonfitz/marquee)](LICENSE)

Marquee turns a Google Nest Hub (or other Cast display) into a clean **Plex or Emby** now-playing display. It shows artwork, title, plot, genres, ratings, media details, progress, and a clock, then returns the display to ambient mode when playback stops. It can also drive an **ESP32/ESPHome** display, which renders the card by polling Marquee's read-only JSON API.

![Marquee Split template](docs/screenshots/split.jpg)

## Templates

Five designed layouts, switchable live from the settings page:

| | |
|:---:|:---:|
| ![Spotlight](docs/screenshots/spotlight.jpg) **Spotlight** — poster beside the full metadata stack | ![Hero](docs/screenshots/hero.jpg) **Hero** — big centered title over the backdrop |
| ![Lower Third](docs/screenshots/lowerthird.jpg) **Lower Third** — broadcast-style chyron over full-bleed art | ![Big Clock](docs/screenshots/bigclock.jpg) **Big Clock** — ambient timepiece with a now-playing strip |

Every template is built from the same blocks — title/logo identity, grouped ratings, metadata chips, plot, progress, clock, poster — so your show/hide toggles, themes, custom accent color, and block position tweaks carry across all of them.

![Settings UI](docs/screenshots/settings.jpg)

## Features

- Live now-playing card from **Plex or Emby** (switchable with one env var),
  with five designed templates: Spotlight, Split, Hero, Lower Third, and Big Clock.
- Four themes plus a custom accent color, 12/24-hour clock styles, and
  per-block show/hide toggles.
- A drag-and-slider editor for moving, sizing, and scaling each card block,
  with an instant demo preview.
- Persisted settings, health checks, and a Docker-first deployment path.
- **Display targets:** Google Cast devices with a screen (Nest Hub, Chromecast)
  with clean idle handoff, plus an **ESP32/ESPHome** path that polls
  `/api/now-playing.json` and renders the card itself.
- A read-only JSON API (`/api/now-playing.json`, CORS-enabled) for ESP32,
  ESPHome, and Home Assistant consumers.

## What You Need

- Docker
- A media server on the same LAN: **Plex** (with an `X-Plex-Token`) **or Emby**
  (with an API key)
- A display on the same LAN: a **Google Cast device with a screen** (Nest Hub,
  Chromecast) **or an ESP32/ESPHome display**

Marquee is designed for a trusted LAN. It has no login and should not be port-forwarded.

### Display compatibility

The Cast path works with **any Google Cast device that has a screen** — not just
Nest Hubs. It uses [catt](https://github.com/skorokithakis/catt) to load the card
via DashCast, so the target must be able to render a web page:

| Device | Works? | Notes |
|---|:---:|---|
| Nest Hub / Hub Max | ✅ | reference target |
| Chromecast / Chromecast w/ Google TV | ✅ | renders on the attached TV |
| TV with Chromecast built-in / Android TV | ✅ usually | DashCast support varies by firmware |
| Nest Mini / Nest Audio / audio-only Cast | ❌ | no screen to render on |

For displays that can't run a browser (a bare ESP32 + LCD), use the ESP32/ESPHome
path instead: the device polls `/api/now-playing.json` and draws the card itself.

## Quick Start

Edit the example IP addresses and token in `compose.yaml`, then run:

```sh
docker compose up -d --build
docker compose logs -f marquee
```

Open `http://SERVER-IP:8084/`. The card served to the Hub is `http://SERVER-IP:8084/image`.

If you prefer plain Docker:

```sh
docker build -t marquee:local .
docker run -d --name marquee --restart unless-stopped --network host \
  -e PAGE_URL=http://192.168.1.10:8084/image \
  -e PLEX_HOST=http://localhost:32400 \
  -e PLEX_TOKEN=replace-me \
  -v marquee-config:/config \
  marquee:local
```

Settings persist under `./data` in Compose mode or `/config` in the container.

## Configuration

Required environment variables:

- `PAGE_URL` — this server's LAN IP + `/image`. The Hub loads this URL, so
  `localhost` will not work here.
- `PLEX_HOST` — keep `http://localhost:32400` when Plex runs on the same
  machine; otherwise its LAN IP
- `PLEX_TOKEN`

(These three are required when `MEDIA_BACKEND=plex`, the default.)

### Choosing the media backend

- `MEDIA_BACKEND` — `plex` (default) or `emby`.
- For Emby, set `EMBY_HOST` (e.g. `http://localhost:8096`) and `EMBY_API_KEY`
  instead of `PLEX_HOST`/`PLEX_TOKEN`.

### Choosing the display target

- `CAST_TARGET` — `nest` (default, Google Cast via `catt`) or `esp32`.
- For a Cast device (default): open the settings page and press **Scan** —
  Marquee discovers Google Cast devices on your LAN and you pick your display
  from a dropdown. (`HUB_IP` still works as an env fallback; discovery needs the
  container on the same network/VLAN as the display, which host networking gives
  you.)
- For an ESP32: set `ESP32_HOST` (and optionally `ESP32_PORT`, default `80`).
  See [ESP32_SETUP.md](ESP32_SETUP.md) and the ESPHome guides below.

Optional settings:

- `MEDIA_USERS` — comma-separated usernames (Plex or Emby) that trigger the
  marquee. Leave empty to react to everyone on the server, including shared and
  home users (the sessions API is server-wide). `PLEX_USERS` is still honored as
  a fallback name.
- `MEDIA_DEVICES` — comma-separated player/device names that may trigger the
  marquee (e.g. `Living Room TV`); empty means any device. `PLEX_DEVICES` is
  honored as a fallback name. Both lists are also editable live on the settings
  page under "Who triggers the marquee." **Device filtering currently applies to
  the Plex backend only**; the Emby path filters by user.
- `TMDB_API_KEY`
- `POLL_SECONDS` default `5`
- `SERVE_PORT` default `8084`
- `REPO_DIR` default `/app`
- `DATA_DIR` default `/config`

Health status is available at `/healthz` and includes the version. A read-only
card-state API is at `/api/now-playing.json` (CORS-enabled) for ESP32/ESPHome/HA.

## Documentation

- **ESP32 / ESPHome displays** — the display polls `/api/now-playing.json` and
  renders the card itself:
  - [ESP32_SETUP.md](ESP32_SETUP.md) — hardware and wiring
  - [docs/ESPHOME/ESPHOME_SETUP.md](docs/ESPHOME/ESPHOME_SETUP.md) and
    [docs/ESPHOME/ESPHOME_CONFIG.md](docs/ESPHOME/ESPHOME_CONFIG.md) — ESPHome YAML
  - [esp32/marquee_display.ino](esp32/marquee_display.ino) — reference custom
    firmware (for tinkerers; hardware-verify before relying on it)
- **Advanced:**
  - [docs/ADVANCED/HOMEASSISTANT_INTEGRATION.md](docs/ADVANCED/HOMEASSISTANT_INTEGRATION.md)
    — optional HA automations (dim-on-play, presence, notifications)
  - [docs/ADVANCED/MULTIPLE_DISPLAYS.md](docs/ADVANCED/MULTIPLE_DISPLAYS.md)
    — running several displays

## Plex Token

1. Sign in to Plex Web and open an item on your server.
2. Select **More (`…`) → Get Info → View XML**.
3. Copy the value after `X-Plex-Token=` from the browser address bar.
4. Test it at `http://PLEX-IP:32400/?X-Plex-Token=YOUR_TOKEN`.

See Plex's [token instructions](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).
Never put a real token in Compose files, screenshots, issues, or commits.

For credits-scene badges, create a TMDb account, open **Account Settings → API**, request a key, and set `TMDB_API_KEY`.

## Tips

**Silence the cast chime.** Every time Marquee takes over the display, the
Nest Hub plays its connect sound. That chime comes from the device, not from
Marquee, and there's a switch for it: open the **Google Home** app → tap
your Hub → **Settings (gear) → Accessibility** → turn off **Play sounds on
start/end of casting**. One-time change; casting is silent afterwards.

## Development

```sh
docker build -t marquee:test .
docker run --rm marquee:test python cast/cast.py --selftest
docker logs -f marquee
```

The service uses [catt](https://github.com/skorokithakis/catt) to launch DashCast on the Hub. Ratings come from Plex metadata; optional credits-scene keywords come from TMDb.

### Cast behavior

Marquee checks that DashCast is active, casts the `/image` URL when playback starts, and releases the Hub when playback stops. Container tests cannot prove physical Hub behavior, so before publishing a release:

1. Open `PAGE_URL` from another LAN device.
2. Start a Plex movie or episode and confirm the Hub loads the card.
3. Pause and resume playback and confirm the progress state updates within one poll interval.
4. Stop playback and confirm the Hub returns to ambient mode.
5. Review `docker logs marquee`; there should be no `catt ... failed` message.
