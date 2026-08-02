# Marquee on an ESP32 panel (CrowPanel 7.0")

An alternative display target: instead of casting the card to a Google Nest Hub,
render it on an ESP32 touch panel running [ESPHome](https://esphome.io).

`marquee-crowpanel.yaml` targets the **Elecrow CrowPanel "Basic" HMI 7.0"**
(ESP32-S3-WROOM-1-N4R8, 800×480 RGB IPS + GT911 touch). Other panels need
different display pins — this file is specific to that board.

> **Status:** starting sketch, not yet run on hardware. The RGB timings and the
> `http_request`/`online_image`/`json` syntax may need tuning to your exact unit
> and ESPHome version. See the caveats at the bottom.

## How it works — pull, not push

Marquee's built-in ESP32 target (`CAST_TARGET=esp32`) *pushes* to the panel
(`POST /display`, `POST /stop`, polls `/status`). ESPHome can't cleanly expose
those routes, and doesn't need to: `now-playing.json` is self-describing
(`{"playing": false}` when idle, the full card when active) and CORS-enabled.

So this panel **polls Marquee itself** every few seconds and shows/hides the card
based on the `playing` field. **Leave Marquee on `CAST_TARGET=nest` (or unset)** —
the panel is self-driven; you do *not* set `ESP32_HOST` for this to work.

## Install (Unraid ESPHome dashboard)

1. In the ESPHome dashboard, create a new device (any name) and open its YAML editor.
2. Paste the contents of `marquee-crowpanel.yaml` (or drop the file into the
   ESPHome config folder and open it).
3. Edit the one value at the top:
   ```yaml
   substitutions:
     marquee_host: "192.168.1.10"   # <-- your Marquee server's LAN IP (same host as PAGE_URL)
     marquee_port: "8084"
   ```
4. Wi-Fi comes from your existing `secrets.yaml` via `!secret wifi_ssid` /
   `!secret wifi_password`. If your secret keys are named differently, rename them
   in the YAML.
5. **Install → Plug into this computer** for the first flash (USB-C). The
   ESP32-S3 needs a wired flash the first time; OTA works for every update after.
6. Once online it appears in the dashboard; logs show it polling `now-playing.json`.

## First boot — what to expect

- Black screen with the backlight off when nothing is playing (the panel sleeps).
- Start a movie/episode on your media server → within ~5 s the backlight wakes and
  the poster + title + year + tagline draw.
- Watch the ESPHome logs for the poll GETs and any JSON/HTTP errors.

## Caveats / tuning

- **PSRAM is required** and already enabled (octal) — the 800×480 framebuffer plus
  JPEG decode won't fit in internal RAM.
- **Display timings** (`hsync_*`/`vsync_*` porches, `pclk_inverted`, `pclk_pin`)
  come from the community config for this board. Tearing, wrong colors, or a black
  panel usually means one of these needs adjusting for your unit.
- **ESPHome version drift:** the `http_request` `on_response` body variable and
  `json::parse_json` signature have changed across releases — match your installed
  version if the compile complains.
- **Touch** (GT911) is commented out — a passive marquee doesn't need it. Enable it
  from the board schematic if you want interactivity later.

## Documentation for the board (it ships with none)

- Elecrow wiki — [CrowPanel 7.0" **with ESPHome**](https://www.elecrow.com/wiki/CrowPanel_ESP2_7.0-inch_with_ESPHome.html)
- Elecrow wiki — [CrowPanel 7.0" hardware / schematic / pinout](https://www.elecrow.com/wiki/esp32-display-702727-intelligent-touch-screen-wi-fi26ble-800480-hmi-display.html)
- espboards.dev — [configuring the Elecrow 7" in ESPHome](https://www.espboards.dev/blog/esphome-configuring-elecrow-7-inch-display/) (source of the pin map used here)
- ESPHome devices — [Elecrow CrowPanel 5" sibling](https://devices.esphome.io/devices/elecrow-5inch-esp32-display/)

## Two ways to drive the panel

- **Screenshot mode (recommended, pixel-perfect):** run the optional
  `marquee-shot` sidecar (`docker compose --profile panel up -d`) and flash
  `marquee-crowpanel-shot.yaml`. The panel displays the real card image; nothing
  is reconstructed on-device.
- **On-device modes (no sidecar):** `marquee-crowpanel.yaml` (lambda card) or
  `marquee-crowpanel-lvgl.yaml` (LVGL card) reconstruct the card from
  `now-playing.json` + art on the ESP itself. Kept as sidecar-free fallbacks.

Note: ESPHome 2026.7's LVGL needs `buffer_size: 5%` on this 800×480 RGB panel or
WiFi's internal RAM is starved; screenshot mode avoids LVGL entirely.
