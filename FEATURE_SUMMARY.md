# Feature Branch Summary: Emby + ESP32 Support

> ### ⚠️ Test branch — nothing here is verified
>
> This document describes work in progress on `feature/emby-esp32-support`, a
> fork of [Jamisonfitz/marquee](https://github.com/Jamisonfitz/marquee). The
> Emby backend and the ESP32 display target are **new, unreleased, and have not
> been tested in a real deployment.** Code here is exercised only by
> `python cast/cast.py --selftest`.
>
> Read this as a description of intent, not a procedure known to work.

**Branch**: `feature/emby-esp32-support`

**Status**: Implemented, partially verified — not yet fully verified end-to-end
against real hardware/servers. See breakdown below before treating this as
"done."

## What this branch adds

Two additive seams inside the existing single-file app (`cast/cast.py`), each
selected by an environment variable, each defaulting to the original
behavior:

- A **media backend** seam (`MEDIA_BACKEND=plex|emby`) so Marquee can read
  now-playing state from Emby as well as Plex.
- A **device target** seam (`CAST_TARGET=nest|esp32`) so Marquee can drive an
  ESP32-based display as well as a Nest/Google Cast device.

No new modules or services were introduced. Everything lives in
`cast/cast.py`, plus a reference Arduino sketch (`esp32/marquee_display.ino`)
for anyone building a custom ESP32 display. (An earlier draft of the project
docs described a separate module/service split that was never built; this has
been corrected.)

## Status by piece

### Emby backend — implemented, unit/mock-verified
- `emby_current_session()` / `parse_emby_session()` are implemented and
  covered by unit tests / mocked responses.
- **Not yet done:** live verification against a real Emby server. The user
  has one available; this is the next step before calling Emby support
  fully verified.

### ESP32 device target + firmware — implemented, hardware-unverified
- `esp32_show` / `esp32_hide` / `device_available()` / `device_active()` for
  `CAST_TARGET=esp32` are implemented.
- `esp32/marquee_display.ino` is a reference firmware sketch implementing the
  `POST /display`, `POST /stop`, `POST /brightness`, `GET /status`, `GET
  /info` contract (requires ArduinoJson 7 + ESP32 core 3.x).
- **Not yet done:** running any of this against real ESP32 hardware. A board
  is on order; until it arrives this path is implemented but unverified.
- The ESPHome route (device polls `/api/now-playing.json` itself) is an
  alternative to the custom firmware and doesn't require the .ino at all —
  see `docs/ESPHOME/` and `ARCHITECTURE_EMBY_ESP32.md`.

### Plex + Nest — unchanged
- Existing behavior is untouched. Guarded by `python cast/cast.py --selftest`.

### Documentation — updated
- `ARCHITECTURE_EMBY_ESP32.md`, `IMPLEMENTATION_GUIDE.md`, and
  `QUICK_REFERENCE.md` were rewritten to describe the actual `cast/cast.py`
  implementation (no fabricated modules/services).

## Before calling this branch done

- [ ] Verify Emby backend against a real Emby server (not just mocks).
- [ ] Verify ESP32 target + firmware against real hardware once the board
      arrives.
- [ ] Re-run `python cast/cast.py --selftest` after any further changes to
      confirm Plex + Nest still pass.
