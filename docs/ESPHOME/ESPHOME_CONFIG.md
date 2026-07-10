# ESPHome Configuration for Marquee

> ### ⚠️ Test branch — never run on hardware
>
> This document describes work in progress on `feature/emby-esp32-support`, a
> fork of [Jamisonfitz/marquee](https://github.com/Jamisonfitz/marquee).
> **No ESP32, no display panel, and no Cast device has ever run this code.**
> The wiring, the YAML, and the firmware here are untested proposals: pin
> assignments, timings, and library calls may simply be wrong.
>
> Nothing below should be trusted until you have verified it yourself. Expect
> to debug. Please report what you find.

How to configure your ESPHome device to display Marquee cards.

## Overview

ESPHome uses **YAML configuration** to define your device behavior. No coding required.

The basic idea:
1. **Poll** Marquee's `/api/now-playing.json` every 5 seconds
2. **Parse** the JSON to extract title, progress, etc.
3. **Render** it on your display
4. **Repeat**

That's it. ESPHome handles the HTTP, parsing, and rendering.

---

## Minimal Configuration

This is the bare minimum to get started:

```yaml
esphome:
  name: marquee-display
  platform: esp32
  board: esp-wrover-kit

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  # Optional: fast_connect for quicker startup
  fast_connect: true

api:
  # Enables Home Assistant integration (optional)
  # Also enables OTA updates

ota:
  password: "your-ota-password"

# Enable logging to serial monitor
logger:
  level: DEBUG

# SPI configuration (for display)
spi:
  clk_pin: GPIO18
  mosi_pin: GPIO23
  miso_pin: GPIO19  # Optional, for reading

# Display definition
display:
  - platform: ili9341
    id: my_display
    cs_pin: GPIO15
    dc_pin: GPIO2
    reset_pin: GPIO4
    rotation: 1  # 0=portrait, 1=landscape, etc.
    data_rate: 40MHz
    pages:
      - id: marquee_page
        lambda: |-
          // Marquee card display
      - id: idle_page
        lambda: |-
          // Idle/clock display

# HTTP client used to fetch Marquee JSON
http_request:
  id: http_client
  useragent: marquee-display
  timeout: 5s

# Globals hold the parsed fields the display reads. NOT a text_sensor — see
# "Why not a text_sensor?" below.
globals:
  - id: np_playing
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: np_title
    type: std::string
    restore_value: no

# Poll on an interval, parse the JSON body in a lambda, store into globals
interval:
  - interval: 5s
    then:
      - http_request.get:
          url: "http://192.168.1.10:8084/api/now-playing.json"
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing) = root["playing"] | false;
                      id(np_title)   = root["title"]   | std::string("");
                      return true;
                    });
                  }
              - if:
                  condition:
                    lambda: 'return id(np_playing);'
                  then:
                    - display.page.show: marquee_page
                  else:
                    - display.page.show: idle_page
              - component.update: my_display
```

### Why not a `text_sensor`?

You'll find older examples (and earlier drafts of these docs) that poll with a
`text_sensor: platform: http_request` and stash the *entire* `now-playing.json`
response in the sensor's `state`. **Don't do that.** ESPHome text/string values
are capped at roughly 255 bytes — Marquee's card JSON (title, subtitle,
summary, genres, scores, progress, etc.) is routinely larger than that, so the
sensor silently truncates it and any `json::parse_json()` call on the
truncated text either fails or returns garbage fields.

The fix is the pattern above: use the `http_request` component's GET **action**
on an `interval:`, capture the response with `capture_response: true`, and
parse the JSON straight out of the response `body` in the `on_response`
lambda — never through a size-limited sensor. Save only the specific fields
you need into `globals:` (or template sensors), and have the display read
those globals directly.

The exact action syntax (`capture_response`, `on_response`, `response->...`)
has evolved across ESPHome releases, so check the current
[`http_request` component docs](https://esphome.io/components/http_request.html)
for your installed version if something doesn't compile — this doc targets a
reasonably recent ESPHome (2024.6+).

### Key Variables

Replace these with your values:

| Variable | Example | Notes |
|----------|---------|-------|
| `name` | `marquee-display` | Device name (no spaces) |
| `wifi_ssid` | `MY_WIFI` | Put in `secrets.yaml` |
| `wifi_password` | `password123` | Put in `secrets.yaml` |
| `url` | `http://192.168.1.10:8084/api/now-playing.json` | Your Marquee server URL |
| `cs_pin` | `GPIO15` | Chip select (match your wiring) |
| `dc_pin` | `GPIO2` | Data/Command |
| `reset_pin` | `GPIO4` | Reset |
| `rotation` | `1` | 0-3 depending on orientation |

---

## Setup Instructions

### Step 1: Create `secrets.yaml`

In the same directory as your YAML config:

```yaml
# secrets.yaml
wifi_ssid: "YOUR_SSID"
wifi_password: "your_password_here"
ota_password: "ota_password_here"
```

**Security**: Don't commit `secrets.yaml` to git.

### Step 2: Get Your Marquee Server URL

Find your Marquee server's IP:
```bash
# If running locally in Docker
docker inspect <marquee-container-id> | grep IPAddress

# Or check your router for the container's IP
# Usually something like 192.168.1.10
```

Test the API:
```bash
curl http://192.168.1.10:8084/api/now-playing.json
```

You should get JSON like:
```json
{
  "playing": false,
  "type": null,
  "title": null,
  "year": null,
  "subtitle": null,
  "state": null,
  "progress": null,
  "summary": null,
  "genres": [],
  "scores": {},
  "poster": false,
  "backdrop": false,
  "logo": false,
  "runtime": null,
  "media": null,
  "contentRating": null
}
```

### Step 3: Configure Display

Update these in your YAML:
- `cs_pin`, `dc_pin`, `reset_pin` — match your wiring
- `rotation` — test different values (0-3)
- `url` in the `http_request.get` action — point to your Marquee server

### Step 4: Upload

**Via web.esphome.io (easiest):**
1. Go to https://web.esphome.io
2. Connect ESP32 via USB
3. Click "CONNECT"
4. Create new device or open existing
5. Paste your YAML
6. Click "Install"

**Via command line:**
```bash
esphome run config.yaml
```

### Step 5: Monitor

After upload:
1. Open **serial monitor** at 115200 baud
2. You should see:
   ```
   [D][esphome.component:094]: Component loop took x ms.
   [D][http_request:066]: Sending GET request to http://192.168.1.10:8084/api/now-playing.json
   [D][http_request:XXX]: Response status: 200
   ```
3. Play something in Plex/Emby
4. Display should update within 5 seconds

---

## Rendering the Card (Lambda)

The `lambda` code in each page is where you draw to the display. Because the
`interval:` action already parsed the JSON into `globals:`, the page lambdas
below just read those globals — they never touch the HTTP response directly.

### Basic Example: Display Title

```yaml
globals:
  - id: np_playing
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: np_title
    type: std::string
    restore_value: no

http_request:
  id: http_client
  useragent: marquee-display
  timeout: 5s

interval:
  - interval: 5s
    then:
      - http_request.get:
          url: "http://192.168.1.10:8084/api/now-playing.json"
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing) = root["playing"] | false;
                      id(np_title)   = root["title"]   | std::string("");
                      return true;
                    });
                  }
              - component.update: my_display

display:
  - platform: ili9341
    id: my_display
    # ... other config ...
    pages:
      - id: marquee_page
        lambda: |-
          // Clear screen
          it.fill(COLOR_BLACK);

          // Draw title (read from the global, not the HTTP response)
          it.printf(10, 10, id(my_font), COLOR_WHITE, "%s", id(np_title).c_str());
```

### Complete Example: Title + Progress

Add more globals for the fields you want, populate them all in the same
`interval:` lambda, then read them from any page:

```yaml
globals:
  - id: np_playing
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: np_title
    type: std::string
    restore_value: no
  - id: np_runtime
    type: std::string
    restore_value: no
  - id: np_genres
    type: std::string
    restore_value: no
  - id: np_offset_ms
    type: int
    restore_value: no
    initial_value: '0'
  - id: np_duration_ms
    type: int
    restore_value: no
    initial_value: '0'

http_request:
  id: http_client
  useragent: marquee-display
  timeout: 5s

interval:
  - interval: 5s
    then:
      - http_request.get:
          url: "http://192.168.1.10:8084/api/now-playing.json"
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing) = root["playing"] | false;
                      id(np_title)   = root["title"]   | std::string("");
                      id(np_runtime) = root["runtime"] | std::string("");

                      if (root["progress"].is<JsonObject>()) {
                        id(np_offset_ms)   = root["progress"]["offsetMs"]   | 0;
                        id(np_duration_ms) = root["progress"]["durationMs"] | 0;
                      } else {
                        id(np_offset_ms) = 0;
                        id(np_duration_ms) = 0;
                      }

                      std::string genres;
                      if (root["genres"].is<JsonArray>()) {
                        for (JsonVariant g : root["genres"].as<JsonArray>()) {
                          if (!genres.empty()) genres += ", ";
                          genres += g.as<std::string>();
                        }
                      }
                      id(np_genres) = genres;
                      return true;
                    });
                  }
              - if:
                  condition:
                    lambda: 'return id(np_playing);'
                  then:
                    - display.page.show: marquee_page
                  else:
                    - display.page.show: idle_page
              - component.update: my_display

display:
  - platform: ili9341
    id: my_display
    # ... config ...
    pages:
      - id: marquee_page
        lambda: |-
          // Fill background
          it.fill(COLOR_BLACK);

          // Title
          it.printf(10, 20, id(large_font), COLOR_WHITE, "%s",
                   id(np_title).c_str());

          // Runtime
          if (!id(np_runtime).empty()) {
            it.printf(10, 60, id(small_font), COLOR_GRAY, "%s",
                     id(np_runtime).c_str());
          }

          // Progress bar
          if (id(np_duration_ms) > 0) {
            float percent = (float)id(np_offset_ms) / id(np_duration_ms);
            int bar_width = (int)(300 * percent);  // 300px total
            it.rectangle(10, 100, 300, 20);         // Outline
            it.filled_rectangle(10, 100, bar_width, 20);  // Fill

            // Percentage text
            it.printf(310, 100, id(small_font), COLOR_WHITE,
                     "%d%%", (int)(percent * 100));
          }

          // Genres
          if (!id(np_genres).empty()) {
            it.printf(10, 130, id(small_font), COLOR_YELLOW, "%s", id(np_genres).c_str());
          }

      - id: idle_page
        lambda: |-
          it.fill(COLOR_BLACK);
          it.printf(10, 10, id(my_font), COLOR_WHITE, "Marquee Ready");
          it.printf(10, 50, id(small_font), COLOR_GRAY, "Waiting for content...");
```

### Define Fonts

Add before your display config:

```yaml
font:
  - file: "gfonts://Roboto"
    id: my_font
    size: 24
  - file: "gfonts://Roboto"
    id: large_font
    size: 32
  - file: "gfonts://Roboto"
    id: small_font
    size: 16
```

---

## Display Strategies

### Strategy 1: Full-Screen (Recommended for simple setups)

Show Marquee card when playing, idle screen when not. The page switch happens
inside the `interval:` lambda (see the "Complete Example" above), right after
the globals are updated:

```yaml
interval:
  - interval: 5s
    then:
      - http_request.get:
          url: "http://192.168.1.10:8084/api/now-playing.json"
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing) = root["playing"] | false;
                      id(np_title)   = root["title"]   | std::string("");
                      return true;
                    });
                  }
              - if:
                  condition:
                    lambda: 'return id(np_playing);'
                  then:
                    - display.page.show: marquee_page
                  else:
                    - display.page.show: idle_page
              - component.update: my_display
```

---

### Strategy 2: Persistent Widget (For larger displays)

Marquee lives in corner, other content fills rest. The page lambda reads the
same globals populated by the `interval:` action above — it doesn't parse
JSON itself:

```yaml
display:
  - platform: ili9341
    id: my_display
    pages:
      - id: marquee_widget
        lambda: |-
          // Draw main dashboard on left 70%
          it.rectangle(0, 0, 224, 240);  // 70% of 320
          it.printf(10, 10, id(my_font), COLOR_WHITE, "Dashboard");

          // Draw Marquee widget on right 30%
          it.rectangle(224, 0, 96, 240);  // 30% of 320

          if (id(np_playing)) {
            it.printf(230, 10, id(small_font), COLOR_YELLOW,
                     "%s", id(np_title).c_str());
          } else {
            it.printf(230, 10, id(small_font), COLOR_GRAY, "No content");
          }
```

---

## Optional: Brightness Control

Add a button or PWM output to control display brightness:

```yaml
# PWM output for backlight
output:
  - platform: ledc
    pin: GPIO12
    frequency: 1000Hz
    id: backlight_pwm

# Light entity for brightness control
light:
  - platform: monochromatic
    output: backlight_pwm
    name: "Display Brightness"
    id: display_brightness
    default_transition_length: 0s

# Optional: Button to toggle brightness
button:
  - platform: template
    name: "Brightness Up"
    on_press:
      then:
        - light.turn_on:
            id: display_brightness
            brightness: 100%

  - platform: template
    name: "Brightness Down"
    on_press:
      then:
        - light.turn_on:
            id: display_brightness
            brightness: 50%
```

---

## Testing & Debugging

### View Serial Monitor Output

```bash
# Via ESPHome CLI
esphome logs config.yaml

# Or via Arduino Serial Monitor at 115200 baud
```

### Common Issues

**"Resource not found (404)"**
- Verify Marquee server URL
- Check firewall isn't blocking port 8084
- Ensure Marquee is running: `curl http://192.168.1.10:8084/api/now-playing.json`

**"JSON parse error"**
- Print the raw response to serial (see "Add Debug Logging" below)
- Verify API is returning valid JSON
- Check field names match your lambda code
- If fields look truncated or cut off mid-string, you're probably back on
  the old `text_sensor` pattern — see "Why not a text_sensor?" above

**Display doesn't update**
- Check the `interval:` period (default 5s in these examples)
- Verify the `on_response` lambda is being called (add debug print)
- Check display is rendering (try simple test first)

### Add Debug Logging

```yaml
logger:
  level: DEBUG
  logs:
    http_request: DEBUG

interval:
  - interval: 5s
    then:
      - http_request.get:
          url: "http://192.168.1.10:8084/api/now-playing.json"
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  ESP_LOGD("marquee", "Status: %d, body: %s",
                           response->status_code, body.c_str());
```

---

## Examples

See the `EXAMPLES/` directory for ready-to-use configurations:
- `basic_display.yaml` — Simple, full-screen
- `interrupt_model.yaml` — Dashboard + interrupt
- `widget_sidebar.yaml` — Persistent sidebar
- `multi_display.yaml` — Multiple devices

---

## Next Steps

✅ You have a working ESPHome device  
✅ It's fetching Marquee JSON  
✅ It's rendering on your display  

🎯 **Want to customize rendering?** Check EXAMPLES/  
🎯 **Want to add brightness control?** See "Brightness Control" above  
🎯 **Having issues?** See "Debugging" section  
🎯 **Ready for Home Assistant?** See ADVANCED/HOMEASSISTANT_INTEGRATION.md  
