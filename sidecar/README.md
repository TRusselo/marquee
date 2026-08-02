# marquee-shot (optional ESP-panel sidecar)

Renders Marquee's real card page to `card.jpg` and serves it, so an ESP32 panel
can display the pixel-perfect card instead of reconstructing it. **Optional** —
Nest Hub users never need this.

## How it works

A warm headless-Chromium page stays open on `${MARQUEE_URL}/image` (the same card
the Nest Hub loads). On a play-aware loop it screenshots that page to `card.jpg`
and serves it from a tiny stdlib HTTP server. Marquee itself is untouched.

Endpoints (on `SERVE_PORT`):
- `GET /card.jpg` — the current 800×480 card image.
- `GET /state.json` — `{"ver": N, "playing": bool}`. `ver` bumps on every new
  frame, so a client (the ESP panel) polls this cheaply and only re-downloads
  `card.jpg` when `ver` changes.

## Run

Opt-in via the `panel` Compose profile (from the repo root):

    docker compose --profile panel up -d --build

A plain `docker compose up -d` does **not** build or start it.

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `MARQUEE_URL` | `http://127.0.0.1:8084` | Marquee base URL |
| `PANEL_WIDTH` / `PANEL_HEIGHT` | `800` / `480` | render size = your panel's pixels |
| `POLL_EVERY` | `1` | seconds between now-playing checks (state-change reaction) |
| `PROGRESS_EVERY` | `60` | seconds between progress-bar heartbeat re-renders |
| `SEEK_MS` | `5000` | position jump (ms) treated as a seek → immediate re-render |
| `JPEG_QUALITY` | `85` | output JPEG quality |
| `SERVE_PORT` | `8088` | port that serves `/card.jpg` |
| `SETTLE_SECONDS` | `0.8` | delay after reload before capture, so the card is fresh |

Re-renders happen on **state change** (play/pause/stop/title/seek) for fast
reaction, plus a slow `PROGRESS_EVERY` heartbeat while playing. Chromium is idle
when nothing is playing.

**Other displays:** set `PANEL_WIDTH`/`PANEL_HEIGHT` to your panel's resolution —
the card is responsive and reflows to it. No code changes.

## Test

    python3 shot.py --selftest      # pure logic, no browser/network needed
    python3 shot.py --once out.jpg  # one render (needs Playwright + Chromium)
