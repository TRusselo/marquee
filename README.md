# Marquee

[![Top language](https://img.shields.io/github/languages/top/TRusselo/marquee)](https://github.com/TRusselo/marquee)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Upstream](https://img.shields.io/badge/fork%20of-Jamisonfitz%2Fmarquee-blue?logo=github)](https://github.com/Jamisonfitz/marquee)
[![License](https://img.shields.io/github/license/TRusselo/marquee)](LICENSE)

Marquee turns a Google Nest Hub (or other Cast display) into a clean **Plex, Emby, or Jellyfin** now-playing display. It shows artwork, title, plot, genres, ratings, media details, progress, and a clock, then returns the display to ambient mode when playback stops. It can also drive an **ESP32/ESPHome** display, which renders the card by polling Marquee's read-only JSON API.

> ### ⚠️ This is a test branch
>
> Upstream [Jamisonfitz/marquee](https://github.com/Jamisonfitz/marquee) is the
> original — Plex + Google Cast, released and working. Everything below that
> isn't Emby, ESP32, or a vertical poster view is his work, and this fork
> tracks his releases (currently **v1.6.0**).
>
> The additions here are **new and unreleased.** How far each has been proven:
> the whole app passes `python cast/cast.py --selftest`; both the **Emby** and
> **Jellyfin** paths have been run end to end — a live server through to the card
> rendering on a real Google Nest Hub. **The ESP32 / ESPHome display path has
> never run on hardware.** If you came here from upstream's README looking for
> Emby, Jellyfin, or ESP32, treat ESP32 as a work in progress, not a drop-in
> replacement.
>
> What's added here:
>
> - **Emby** as a media backend, alongside Plex (`MEDIA_BACKEND=emby`)
> - **Jellyfin** as a media backend (`MEDIA_BACKEND=jellyfin`) — shares the Emby
>   code path, since Jellyfin is an API-compatible fork of Emby
> - **ESP32 / ESPHome** as a display target, alongside Google Cast
> - A richer now-playing payload (cast, chapters, tagline, tracks, play method)
> - Home Assistant notes and multi-display guides
>
> There is no published container image for this fork — build it yourself
> (see [Quick Start](#quick-start)). Please file fork-specific issues here
> rather than upstream. Reports from anyone who does run it on hardware are
> very welcome.

![One app, many looks — templates × themes × fonts](docs/screenshots/variety.jpg)

*Same app, nine looks: six templates × eight themes × six fonts × any accent color.*

With your own library it looks like this — real posters, backdrops, and clear-logos straight from Plex:

| | |
|:---:|:---:|
| ![Street with a real library](docs/screenshots/live-street.jpg) | ![Spotlight with a real library](docs/screenshots/live-spotlight.jpg) |

## Templates

Six designed layouts, switchable live from the settings page:

| | |
|:---:|:---:|
| ![Spotlight](docs/screenshots/spotlight.jpg) **Spotlight** — poster beside the full metadata stack | ![Hero](docs/screenshots/hero.jpg) **Hero** — big centered title over the backdrop |
| ![Lower Third](docs/screenshots/lowerthird.jpg) **Lower Third** — broadcast-style chyron over full-bleed art | ![Big Clock](docs/screenshots/bigclock.jpg) **Big Clock** — ambient timepiece with a now-playing strip |
| ![Street](docs/screenshots/street.jpg) **Street** — a living night scene: your poster in a bulb-lit marquee, the movie logo sprayed on brick | ![Split](docs/screenshots/split.jpg) **Split** — hard split: full-height art wall beside the info column |

Every template is built from the same blocks — title/logo identity, grouped ratings, metadata chips, plot, progress, clock, poster — so your show/hide toggles, themes, custom accent color, and block position tweaks carry across all of them.

![Settings UI](docs/screenshots/settings.jpg)

## Features

- Live now-playing card from **Plex, Emby, or Jellyfin** (switchable with one env var),
  with six designed templates: Spotlight, Split, Hero, Lower Third, Big Clock,
  and Street (animated marquee bulbs and all).
- Eight themes, one-tap Vibe presets, a custom accent color, five title
  fonts, a card font, 12/24-hour clock styles, and per-block show/hide toggles.
- Export and import your whole setup as text, so a look can be shared.
- Session filters: limit casting to your users and your devices, live
  from the settings page — shared users no longer take over the display.
- A drag-and-slider editor for moving, sizing, justifying, and scaling each
  card block, with an instant demo preview featuring original fictional
  films (no copyrighted art).
- Persisted settings, health checks, and a Docker-first deployment path.
- **Display targets:** Google Cast devices with a screen (Nest Hub, Chromecast)
  with clean idle handoff, plus an **ESP32/ESPHome** path (untested) where
  Marquee POSTs the card's JSON URL to the panel and the panel renders it.
- A read-only JSON API (`/api/now-playing.json`, CORS-enabled) for ESPHome and
  Home Assistant consumers. (The ESP32 push path hands the panel the plain
  `/now-playing.json` URL, derived from `PAGE_URL`'s origin.)

## What You Need

- Docker
- A media server on the same LAN: **Plex** (with an `X-Plex-Token`), **Emby**,
  **or Jellyfin** (with an API key)
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

- `MEDIA_BACKEND` — `plex` (default), `emby`, or `jellyfin`.
- For Emby, set `EMBY_HOST` (e.g. `http://localhost:8096`) and `EMBY_API_KEY`
  instead of `PLEX_HOST`/`PLEX_TOKEN`.
- For Jellyfin, set `MEDIA_BACKEND=jellyfin` with `JELLYFIN_HOST` (e.g.
  `http://localhost:8096`) and `JELLYFIN_API_KEY`. Jellyfin is an
  API-compatible fork of Emby, so it shares the Emby code path — the `EMBY_*`
  names also work if you prefer them. Verified against Jellyfin 10.11.

### Choosing the display target

- `CAST_TARGET` — `nest` (default, Google Cast via `catt`) or `esp32`.
- For a Cast device (default): open the settings page and either press **Scan**
  to pick a discovered device, or **type the display's IP address**. See
  [Finding your cast device](#finding-your-cast-device) below.
- For an ESP32: set `ESP32_HOST` (and optionally `ESP32_PORT`, default `80`).
  See [ESP32_SETUP.md](ESP32_SETUP.md) and the ESPHome guides below.

### Finding your cast device

**Scan is a convenience, not the source of truth.** Press it and Marquee runs
`catt scan`, which discovers Google Cast devices by **mDNS** — multicast DNS,
the same mechanism behind `.local` hostnames. Whatever it finds is offered as
suggestions in the Cast device field.

mDNS is multicast, and multicast is the first thing networks drop. It commonly
fails when:

- the container is on a Docker bridge network rather than the host's (mDNS does
  not cross the NAT) — use `network_mode: host`, as `compose.yaml` does;
- the display sits on a different VLAN or subnet from the server, and the router
  does not forward multicast or run an mDNS reflector/repeater;
- an access point has *AP isolation* or *multicast filtering* enabled — common
  defaults on mesh and enterprise gear;
- IGMP snooping is on and no querier is present, so multicast never reaches the
  wired segment.

A device that scan cannot see is usually still perfectly reachable. Discovery
and connection are separate: `catt` talks to a Cast device directly on TCP port
`8009`, which does not involve mDNS at all. This is why the Cast device field
takes a **typed IP address** — on a LAN with several Nest displays, a scan that
returns only one unrelated TV is a routine outcome, not a broken install.

To find a display's IP: check your router's DHCP leases, or open the Google Home
app → tap the device → gear icon → *Device information*. You can sanity-check it
before saving:

```sh
curl -s http://DISPLAY-IP:8008/setup/eureka_info | head -c 200
```

A Cast device answers with JSON containing its `name`. Nothing responds, or the
port is closed? Then the IP is wrong, or the device is off the network — that is
worth knowing *before* you blame Marquee.

Give the display a DHCP reservation. An IP typed into the settings page is
static configuration; if the lease moves, casting stops until you update it.

Optional settings:

- `MEDIA_USERS` — comma-separated usernames (Plex or Emby) that trigger the
  marquee. Leave empty to react to everyone on the server, including shared and
  home users (the sessions API is server-wide). `PLEX_USERS` is still honored as
  a fallback name.
- `MEDIA_DEVICES` — comma-separated player/device names that may trigger the
  marquee (e.g. `Living Room TV`); empty means any device. `PLEX_DEVICES` is
  honored as a fallback name. Both lists are also editable live on the settings
  page under "Who triggers the marquee." Both backends honor both filters —
  Emby matches a session's `DeviceName` or `Client`, Plex its player's
  title/device/product.

When more than one allowed session is playing, each takes the display in turn.
**Rotate between sessions** on the settings page sets how long each gets
(default 30 seconds; 0 pins the first, ordered by user then device). Sessions
are always sorted before one is picked, so the card never flips at random
because the server reordered its session list.

#### These three env vars are defaults, not overrides

`HUB_IP`, `MEDIA_USERS`, and `MEDIA_DEVICES` also exist as fields on the settings
page, and the rule for all three is the same:

> **Type a value to use it. Leave the field empty to inherit the container's.**

The settings page shows each env value as a greyed **placeholder** — `jamison
(from MEDIA_USERS)` — so an empty box reads as *inheriting this*, not *nothing is
set*. Typing a value **replaces** the env var; clearing the box hands control
back to it.

That visibility is the point. Marquee previously *merged* the env list with the
settings list, so `MEDIA_USERS=jamison` in your Compose file left the Users field
looking empty while every other user's session was silently ignored — and no
amount of editing the field could lift it. An invisible filter is a filter that
lies about itself.

One consequence worth stating: while an env var is set, an empty field means
*inherit*, so you cannot express "filter nobody" from the UI. Unset the env var
if you want the settings page to be the whole story.

- `TMDB_API_KEY`
- `POLL_SECONDS` default `5`
- `SERVE_PORT` default `8084`
- `REPO_DIR` — the container sets `/app` (the code's own default is `/repo`)
- `DATA_DIR` — the container sets `/config` (defaults to `REPO_DIR/output`)

Health status is available at `/healthz` and includes the version. A read-only
card-state API is at `/api/now-playing.json` (CORS-enabled) for ESP32/ESPHome/HA.

### Display profiles

Appearance settings are stored per display profile — `cast` for a Google Cast
screen, `esp` for an ESP panel — so a small panel can drop the elements a Hub
has room for. Both profiles share the globals: the Hub's IP, the session
filters, and the weather ZIP.

Each display asks for its own with `?profile=cast|esp`:

- `GET /settings.json?profile=esp` — same-origin, the flat settings the card
  and settings pages have always read, resolved for that profile.
- `GET /api/settings?profile=esp` — CORS-enabled, appearance only, for an
  ESP/ESPHome panel to fetch its own layout. Deliberately omits the globals.
- `POST /save?profile=esp` — writes the globals plus that one profile, leaving
  the other untouched.

Omit `?profile=` and you get the default profile, so anything that predates
profiles keeps working unchanged.

## Documentation

- **ESP32 / ESPHome displays** — the panel fetches the now-playing JSON and
  renders the card itself. **None of this has been run on hardware**; every
  document below opens with that warning:
  - [ESP32_SETUP.md](ESP32_SETUP.md) — hardware and wiring
  - [docs/ESPHOME/ESPHOME_SETUP.md](docs/ESPHOME/ESPHOME_SETUP.md) and
    [docs/ESPHOME/ESPHOME_CONFIG.md](docs/ESPHOME/ESPHOME_CONFIG.md) — ESPHome YAML
  - [esp32/marquee_display.ino](esp32/marquee_display.ino) — reference custom
    firmware, never compiled against a real board
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

## Community Forks & Related Projects

- [TRusselo's fork](https://github.com/TRusselo/marquee) — exploring Emby
  support, ESP32/ESPHome displays, Home Assistant integration, and vertical
  poster views. Independent project, not maintained or supported here, but
  worth a look if that's your stack.

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
