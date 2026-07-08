# ESPHome + Marquee: Overview

**ESPHome is the recommended way to display Marquee cards on a microcontroller display.**

## Why ESPHome?

### The Problem
Want to display now-playing info on an ESP32 display? Normally you'd:
1. Install Arduino IDE
2. Install libraries
3. Write C++ code
4. Handle WiFi, HTTP, JSON parsing
5. Debug hardware issues
6. Manually upload new code

### The ESPHome Solution
```yaml
# That's it. YAML config, no coding required.
esphome:
  name: marquee-display
wifi:
  ssid: YOUR_SSID
  password: YOUR_PASSWORD
display:
  - platform: ili9341
    cs_pin: GPIO15
    dc_pin: GPIO2
http_request:
text_sensor:
  - platform: http_request
    resource: http://marquee-server:8084/api/now-playing.json
    scan_interval: 5s
```

Flash it once via USB (or web browser), then all updates are **OTA (wireless)**.

## What is ESPHome?

**ESPHome** is a firmware framework for ESP32/ESP8266 microcontrollers that:

- **No coding required** — Configuration-driven via YAML
- **40+ display drivers** — ILI9341, ST7789, OLED, e-ink, etc.
- **Built-in WiFi + OTA** — Wireless updates after first flash
- **REST API** — Automatic web server for control
- **Huge community** — Thousands of examples and integrations
- **Home Assistant native** — Seamless HA integration (optional)
- **Sensors & controls** — Add brightness buttons, temp sensors, etc.

## How Marquee + ESPHome Works

### The Flow

```
┌─────────────────────────────────────────────────────┐
│ Plex or Emby Media Server                           │
│ (Someone presses play)                              │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ Marquee Service                                     │
│ - Polls Plex/Emby every 5 seconds                   │
│ - Generates now-playing.json                        │
│ - Serves it at: /api/now-playing.json               │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ ESPHome Device (your display)                       │
│ - Polls /api/now-playing.json every 5 seconds       │
│ - Parses JSON (playing, title, progress, etc.)      │
│ - Renders it on the display                         │
│ - When playback stops, shows idle screen            │
└─────────────────────────────────────────────────────┘
```

### Key Points

✅ **ESPHome is autonomous** — It fetches and renders independently  
✅ **Marquee is simple** — Just generates JSON, doesn't manage devices  
✅ **Multiple displays work** — Each device polls the same endpoint  
✅ **Non-intrusive** — Display can show other things (clock, weather) most of the time  
✅ **Offline-capable** — ESPHome device works on local network only  

## Three Display Strategies

ESPHome is flexible. Depending on your display size and needs, you can:

### Strategy 1: Dedicated Display
**Best for**: A screen just for Marquee

```
┌────────────────────────┐
│                        │
│   Loading...           │  → Shows "Loading..." while fetching
│   (Polling Marquee)    │
│                        │
└────────────────────────┘

        ↓ (content plays)

┌────────────────────────┐
│  Now Playing           │
│                        │
│  Movie Title 2024      │
│  ■■■■■■■░░░ 45%       │
│  2h 14m runtime        │
│                        │
└────────────────────────┘

        ↓ (playback stops)

┌────────────────────────┐
│                        │
│  Marquee Ready         │
│                        │
│  IP: 192.168.1.100     │
│                        │
└────────────────────────┘
```

**Pros**: Simple, clear, focused  
**Cons**: Wasted screen space when idle

---

### Strategy 2: Full-Screen Interrupt
**Best for**: Displays that normally show dashboard/clock

```
Normal State:
┌────────────────────────┐
│  12:34                 │
│  72°F, Sunny           │
│  Tomorrow: Sunny, 68°F │
└────────────────────────┘

        ↓ (play detected)

Interrupt Mode:
┌────────────────────────┐
│  Now Playing           │
│  Movie Title           │
│  S1 • E5 • Episode     │
│  ■■■■■■■░░░ 45%       │
└────────────────────────┘

        ↓ (playback stops)

Back to Normal:
┌────────────────────────┐
│  12:34                 │
│  72°F, Sunny           │
│  Tomorrow: Sunny, 68°F │
└────────────────────────┘
```

**Pros**: Intelligent, multi-purpose, adaptive  
**Cons**: Requires a bit more YAML logic

---

### Strategy 3: Persistent Widget
**Best for**: Larger displays (7"+) that can share space

```
┌──────────────────────────────────────┐
│  12:34  Sunny, 72°F     │ Now: Movie │
│  Tuesday                │ Title 2024 │
│  │ Groceries            │ ■■■■■■■░░ │
│ │ Pick up dry clean     │ 45% 2h14m  │
│ │ Dinner @ 7pm          │            │
│                          │ Genre:     │
│ ┌─────────────────────┐ │ Drama,     │
│ │ Upcoming Events     │ │ Action     │
│ │ Tue: Dentist 3pm    │ │            │
│ │ Wed: Gym 6pm        │ │            │
│ └─────────────────────┘ │            │
└──────────────────────────────────────┘
```

**Pros**: Maximum info density, nothing lost  
**Cons**: Only works on large displays

---

## Getting Started

### Prerequisites

✓ **ESP32 microcontroller** (~$10)  
✓ **Display** (~$15) — ILI9341 recommended  
✓ **WiFi network** (same LAN as Marquee)  
✓ **Marquee server** running (Docker recommended)  
✓ **USB cable** (for initial flashing)  

### Three Steps

1. **Setup Hardware** (ESPHOME_SETUP.md)
   - Wire ESP32 to display
   - Connect USB to computer

2. **Configure ESPHome** (ESPHOME_CONFIG.md)
   - Choose your display strategy
   - Edit YAML config
   - Flash via web browser

3. **Done!**
   - Device automatically fetches Marquee card
   - Updates every 5 seconds
   - No manual intervention needed

## What You Get

✅ **Autonomous display** — Works even if you leave it alone  
✅ **Beautiful cards** — Shows title, progress, rating, runtime  
✅ **Brightness control** — Optional GPIO for backlight PWM  
✅ **Idle handling** — Shows clock or "Marquee Ready" when idle  
✅ **Wireless updates** — OTA (over-the-air) firmware updates  
✅ **Multi-display support** — Run N devices off one Marquee server  
✅ **Home Assistant optional** — Works standalone, integrates with HA if you have it  

## Comparison: ESPHome vs. Custom Firmware

| Feature | ESPHome | Custom Arduino |
|---------|---------|----------------|
| Setup | YAML config | Arduino IDE + code |
| Learning curve | Easy | Medium |
| Flexibility | Very (YAML) | Maximum (C++) |
| Updates | OTA wireless | USB manual |
| Community support | Huge | Smaller |
| Multi-display | Easy | Possible |
| Display options | 40+ built-in | Library-dependent |
| Home Assistant | Native integration | Manual setup |

**Recommendation**: Start with ESPHome. If you need advanced customization later, reference the custom firmware.

## Next Steps

👉 **Ready to get started?** Go to [ESPHOME_SETUP.md](ESPHOME_SETUP.md)

👉 **Want to understand the architecture?** See [ARCHITECTURE_EMBY_ESP32.md](../ARCHITECTURE_EMBY_ESP32.md)

👉 **Prefer custom Arduino code?** See [CUSTOM_FIRMWARE/](../CUSTOM_FIRMWARE/)

## FAQ

**Q: Do I need Home Assistant?**
A: No. ESPHome works standalone. HA integration is optional for advanced automation.

**Q: Can I use this with multiple displays?**
A: Yes! Each ESPHome device polls the same Marquee `/api/now-playing.json` endpoint independently.

**Q: What displays are supported?**
A: Any SPI display (ILI9341, ST7789, etc.) or I2C OLED. ESPHome has 40+ drivers built-in.

**Q: Can my display show other things too?**
A: Absolutely. ESPHome can switch between dashboard, clock, Marquee card, etc.

**Q: What if Marquee server goes down?**
A: Display shows last known state or error message. Retries when server comes back.

**Q: Can I customize the card rendering?**
A: Yes. ESPHome is flexible. You write YAML lambdas to render exactly what you want.

---

**Let's build!** 🎨
