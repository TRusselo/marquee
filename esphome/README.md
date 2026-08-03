# Marquee on an ESP32 panel (CrowPanel 7.0")

Instead of casting the now-playing card to a Google Nest Hub, show it on an ESP32
touch panel running [ESPHome](https://esphome.io). Built and tested on the
**Elecrow CrowPanel "Basic" HMI 7.0"** (ESP32-S3-WROOM-1-N4R8, 800×480 RGB IPS +
GT911 touch). Other panels need different display pins/timings.

All methods are **pull-based**: the panel polls Marquee over the LAN and drives
itself. **Leave Marquee on `CAST_TARGET=nest` (or unset)** — you do *not* set any
`ESP32_HOST`.

## Two ways to render the card

### 1. Screenshot sidecar — recommended, pixel-perfect
`marquee-crowpanel-shot.yaml` + the optional **`marquee-shot`** sidecar (headless
Chromium). The sidecar screenshots Marquee's *real* card page to a JPEG; the panel
just displays that image full-screen — pixel-identical to the Nest Hub card, and
the panel config stays dead simple (no on-device layout).

The sidecar is a **decoupled add-on**: it reads Marquee only over HTTP and never
modifies it, so it runs against **any Marquee, including the upstream image** —
the panel inherits the real card design for free. Published at
`ghcr.io/trusselo/marquee-shot`.

- Enable it — Unraid CA template (`../unraid/marquee-shot.xml`), plain
  `docker run`, or the compose `panel` profile: see `../sidecar/README.md`.
- Flash `marquee-crowpanel-shot.yaml`, pointing `sidecar_host` at wherever the
  sidecar runs.

### 2. On-device render — no sidecar (`examples/`)
The ESP reconstructs the card itself from `now-playing.json` + art. Lighter infra
(no Chromium), but it's a re-creation, not a pixel copy of the cast card.

- `examples/crowpanel-lambda.yaml` — simplest: poster + title + year + tagline via
  the classic display lambda.
- `examples/crowpanel-lvgl.yaml` — "cinematic": full-screen dimmed backdrop +
  title + metadata line via LVGL.

Each example is split into **PART 1 — ESP/CrowPanel hardware** and **PART 2 —
Marquee card logic**, with inline comments explaining what draws on screen.

## Install (ESPHome dashboard)

1. Create a device in the ESPHome dashboard and open its YAML editor (or drop the
   chosen `.yaml` into the ESPHome config folder).
2. Edit the `substitutions` at the top — your Marquee (and sidecar) host IP.
3. Wi-Fi comes from your `secrets.yaml` (`!secret wifi_ssid` / `!secret
   wifi_password`). DHCP by default; a commented `manual_ip` template is included
   if you want a static IP.
4. First flash is over **USB-C** (Install → Plug into this computer). Every update
   after that can be **OTA**.

## What you'll see

- Nothing playing → idle/black screen, backlight dimmed or off.
- Start a title → the card appears within a few seconds and updates on
  play/pause/seek. (End-to-end latency is dominated by Marquee's own `POLL_SECONDS`
  media-server poll, default 5 s.)

## Board specifics / gotchas (learned on hardware)

- **PSRAM required** (octal; N4R8 = 8 MB) — the 800×480 framebuffer + JPEG decode
  buffers won't fit in internal RAM.
- **Console on UART0** (`logger: hardware_uart: UART0`) — ESPHome 2026.7 defaults
  the console to USB-Serial-JTAG, whose pins (GPIO19/20) are this board's **touch
  i2c bus**, so the default makes i2c init kill the console (and destabilize the
  app). Serial logs then appear on `/dev/ttyUSB0` (CH340 = UART0).
- **LVGL `buffer_size: 5%`** — the default (25% ≈ 192 KB) eats the internal DMA
  RAM WiFi needs on this RGB panel, so WiFi won't associate/hold. The screenshot
  method avoids LVGL entirely.
- **Full USB flash rewrites the bootloader** — keep the `CONFIG_SPIRAM_*` options
  and `psram: mode: octal`; without them the second-stage bootloader can hang at
  `entry` on a fresh flash.
- **Display timings** (`hsync_*`/`vsync_*` porches, `pclk_inverted`, `pclk_pin`)
  are for this exact board — wrong colors, tearing, or a black panel usually means
  one of these needs tuning for your unit.

## Documentation for the board (it ships with none)

**Heads-up:** Elecrow's own pages for this device are unreliable — wrong/omitted
pins and stale ESPHome snippets. The **espboards.dev** post below is the most
trustworthy reference; much of it is literally correcting the errors on Elecrow's
page. Prefer it, and treat the Elecrow links as secondary.

- espboards.dev — [configuring the Elecrow 7" in ESPHome](https://www.espboards.dev/blog/esphome-configuring-elecrow-7-inch-display/) — **most reliable; source of the pin map used here**
- Elecrow wiki — [CrowPanel 7.0" with ESPHome](https://www.elecrow.com/wiki/CrowPanel_ESP2_7.0-inch_with_ESPHome.html) (unreliable — cross-check)
- Elecrow wiki — [CrowPanel 7.0" hardware / schematic / pinout](https://www.elecrow.com/wiki/esp32-display-702727-intelligent-touch-screen-wi-fi26ble-800480-hmi-display.html) (unreliable — cross-check)
- ESPHome devices — [Elecrow CrowPanel 5" sibling](https://devices.esphome.io/devices/elecrow-5inch-esp32-display/)
