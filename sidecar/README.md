# marquee-shot (optional ESP-panel sidecar)

Renders Marquee's real card page to `card.jpg` and serves it, so an ESP32 panel
can display the pixel-perfect card instead of reconstructing it. **Optional** —
Nest Hub users never need this.

## How it works

A warm headless-Chromium page stays open on `${MARQUEE_URL}/image` (the same card
the Nest Hub loads). On a play-aware loop it screenshots that page to `card.jpg`
and serves it from a tiny stdlib HTTP server. Marquee itself is untouched.

## Run

Opt-in via the `panel` Compose profile (from the repo root):

    docker compose --profile panel up -d --build

A plain `docker compose up -d` does **not** build or start it.

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `MARQUEE_URL` | `http://127.0.0.1:8084` | Marquee base URL |
| `PANEL_WIDTH` / `PANEL_HEIGHT` | `800` / `480` | render size = your panel's pixels |
| `CAPTURE_EVERY` | `5` | seconds between captures while playing |
| `JPEG_QUALITY` | `85` | output JPEG quality |
| `SERVE_PORT` | `8088` | port that serves `/card.jpg` |
| `SETTLE_SECONDS` | `0.8` | delay before capture so the card reflects new data |

**Other displays:** set `PANEL_WIDTH`/`PANEL_HEIGHT` to your panel's resolution —
the card is responsive and reflows to it. No code changes.

## Test

    python3 shot.py --selftest      # pure logic, no browser/network needed
    python3 shot.py --once out.jpg  # one render (needs Playwright + Chromium)
