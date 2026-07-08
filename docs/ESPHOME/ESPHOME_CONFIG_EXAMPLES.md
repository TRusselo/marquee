# ESPHome Configuration Examples

Ready-to-use YAML configurations for different display strategies.

---

## Example 1: Basic Full-Screen Display

**File**: `basic_display.yaml`

Simplest setup. Shows Marquee card when playing, idle screen otherwise.

```yaml
esphome:
  name: marquee-display
  platform: esp32
  board: esp-wrover-kit

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  fast_connect: true

api:

ota:
  password: !secret ota_password

logger:
  level: INFO

spi:
  clk_pin: GPIO18
  mosi_pin: GPIO23
  miso_pin: GPIO19

display:
  - platform: ili9341
    id: my_display
    cs_pin: GPIO15
    dc_pin: GPIO2
    reset_pin: GPIO4
    rotation: 1
    data_rate: 40MHz
    pages:
      - id: marquee_page
        lambda: |-
          // Reads globals populated by the interval: action below —
          // NOT a text_sensor (see ESPHOME_CONFIG.md, "Why not a text_sensor?")
          it.fill(COLOR_BLACK);

          // Title
          it.printf(10, 20, id(large_font), COLOR_WHITE, "%s",
                   id(np_title).c_str());

          // Subtitle (for episodes)
          if (!id(np_subtitle).empty()) {
            it.printf(10, 60, id(small_font), COLOR_GRAY, "%s", id(np_subtitle).c_str());
          }

          // Progress bar
          if (id(np_duration_ms) > 0) {
            float pct = (float)id(np_offset_ms) / id(np_duration_ms);
            int bar_width = (int)(280 * pct);
            it.rectangle(10, 100, 280, 15);
            it.filled_rectangle(10, 100, bar_width, 15);
          }

          // Runtime
          if (!id(np_runtime).empty()) {
            it.printf(10, 130, id(small_font), COLOR_GRAY, "%s",
                     id(np_runtime).c_str());
          }

          // Genres
          if (!id(np_genres).empty()) {
            it.printf(10, 155, id(small_font), COLOR_YELLOW, "%s", id(np_genres).c_str());
          }

      - id: idle_page
        lambda: |-
          it.fill(COLOR_BLACK);
          it.printf(10, 10, id(large_font), COLOR_WHITE, "Marquee");
          it.printf(10, 50, id(small_font), COLOR_GRAY, "Ready");
          it.printf(10, 80, id(small_font), COLOR_GRAY, "Waiting for content...");

font:
  - file: "gfonts://Roboto"
    id: large_font
    size: 32
  - file: "gfonts://Roboto"
    id: small_font
    size: 16

# Globals hold the fields parsed out of the JSON response. A text_sensor
# would truncate at ~255 bytes, so we never store the raw JSON in one.
globals:
  - id: np_playing
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: np_title
    type: std::string
    restore_value: no
  - id: np_subtitle
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
          url: "http://192.168.1.10:8084/api/now-playing.json"  # CHANGE THIS
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing)  = root["playing"]  | false;
                      id(np_title)    = root["title"]    | std::string("");
                      id(np_subtitle) = root["subtitle"] | std::string("");
                      id(np_runtime)  = root["runtime"]  | std::string("");

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
```

**How to use:**
1. Copy this YAML
2. Change `url:` in the `http_request.get` action to your Marquee server
3. Create `secrets.yaml` with WiFi credentials
4. Upload to your ESP32
5. Done!

> Check the [`http_request` component docs](https://esphome.io/components/http_request.html)
> for your installed ESPHome version — `capture_response`/`on_response` syntax
> requires a reasonably recent release (2024.6+) and has evolved over time.

---

## Example 2: With Brightness Control

**File**: `brightness_control.yaml`

Same as Example 1, but adds GPIO PWM control for display backlight.

```yaml
# ... copy all of Example 1 ...

# Add these sections:

output:
  - platform: ledc
    pin: GPIO12
    frequency: 1000Hz
    id: backlight

light:
  - platform: monochromatic
    output: backlight
    name: "Display Brightness"
    id: display_light
    default_transition_length: 0s

# Optional: Home Assistant service to set brightness
button:
  - platform: template
    name: "Brightness 100%"
    on_press:
      then:
        - light.turn_on:
            id: display_light
            brightness: 100%

  - platform: template
    name: "Brightness 75%"
    on_press:
      then:
        - light.turn_on:
            id: display_light
            brightness: 75%

  - platform: template
    name: "Brightness 50%"
    on_press:
      then:
        - light.turn_on:
            id: display_light
            brightness: 50%

  - platform: template
    name: "Brightness 25%"
    on_press:
      then:
        - light.turn_on:
            id: display_light
            brightness: 25%
```

**New features:**
- PWM backlight control on GPIO12
- Brightness buttons in Home Assistant
- Set to any level from 0-100%

---

## Example 3: Full-Screen Interrupt Model

**File**: `interrupt_model.yaml`

Device shows dashboard (time, weather) normally. When content plays, Marquee takes over full screen.

```yaml
esphome:
  name: marquee-display
  platform: esp32
  board: esp-wrover-kit

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
ota:
  password: !secret ota_password

logger:
  level: INFO

spi:
  clk_pin: GPIO18
  mosi_pin: GPIO23
  miso_pin: GPIO19

time:
  - platform: homeassistant  # Get time from HA (optional)
    id: homeassistant_time

  - platform: sntp  # Fallback to NTP
    id: sntp_time

display:
  - platform: ili9341
    id: my_display
    cs_pin: GPIO15
    dc_pin: GPIO2
    reset_pin: GPIO4
    rotation: 1
    data_rate: 40MHz
    pages:
      # Dashboard (normal state)
      - id: dashboard_page
        lambda: |-
          it.fill(COLOR_BLACK);
          
          // Time
          time_t now = time(nullptr);
          struct tm* timeinfo = localtime(&now);
          char time_str[20];
          strftime(time_str, sizeof(time_str), "%H:%M", timeinfo);
          it.printf(10, 10, id(very_large_font), COLOR_WHITE, "%s", time_str);
          
          // Date
          char date_str[20];
          strftime(date_str, sizeof(date_str), "%A, %b %d", timeinfo);
          it.printf(10, 60, id(large_font), COLOR_GRAY, "%s", date_str);
          
          // Weather (if you have it)
          it.printf(10, 110, id(small_font), COLOR_YELLOW, "72°F, Sunny");
          it.printf(10, 130, id(small_font), COLOR_GRAY, "Tomorrow: 68°F, Clouds");
      
      # Marquee (when playing)
      - id: marquee_page
        lambda: |-
          // Reads globals populated by the interval: action below —
          // NOT a text_sensor (see ESPHOME_CONFIG.md, "Why not a text_sensor?")
          it.fill(COLOR_BLACK);

          // Title
          it.printf(10, 20, id(large_font), COLOR_WHITE, "%s",
                   id(np_title).c_str());

          // Subtitle (episodes)
          if (!id(np_subtitle).empty()) {
            it.printf(10, 60, id(small_font), COLOR_GRAY, "%s",
                     id(np_subtitle).c_str());
          }

          // Progress bar
          if (id(np_duration_ms) > 0) {
            float pct = (float)id(np_offset_ms) / id(np_duration_ms);
            int bar_width = (int)(280 * pct);
            it.rectangle(10, 100, 280, 15);
            it.filled_rectangle(10, 100, bar_width, 15);
            it.printf(300, 100, id(small_font), COLOR_WHITE, "%d%%", (int)(pct*100));
          }

          // Runtime
          if (!id(np_runtime).empty()) {
            it.printf(10, 130, id(small_font), COLOR_GRAY, "%s",
                     id(np_runtime).c_str());
          }

font:
  - file: "gfonts://Roboto"
    id: very_large_font
    size: 48
  - file: "gfonts://Roboto"
    id: large_font
    size: 32
  - file: "gfonts://Roboto"
    id: small_font
    size: 16

# Globals hold the fields parsed out of the JSON response. A text_sensor
# would truncate at ~255 bytes, so we never store the raw JSON in one.
globals:
  - id: np_playing
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: np_title
    type: std::string
    restore_value: no
  - id: np_subtitle
    type: std::string
    restore_value: no
  - id: np_runtime
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
          url: "http://192.168.1.10:8084/api/now-playing.json"  # CHANGE THIS
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing)  = root["playing"]  | false;
                      id(np_title)    = root["title"]    | std::string("");
                      id(np_subtitle) = root["subtitle"] | std::string("");
                      id(np_runtime)  = root["runtime"]  | std::string("");

                      if (root["progress"].is<JsonObject>()) {
                        id(np_offset_ms)   = root["progress"]["offsetMs"]   | 0;
                        id(np_duration_ms) = root["progress"]["durationMs"] | 0;
                      } else {
                        id(np_offset_ms) = 0;
                        id(np_duration_ms) = 0;
                      }
                      return true;
                    });
                  }
              - if:
                  condition:
                    lambda: 'return id(np_playing);'
                  then:
                    - display.page.show: marquee_page
                  else:
                    - display.page.show: dashboard_page
              - component.update: my_display
```

**How it works:**
1. Device shows time + weather on dashboard
2. Every 5 seconds, the `interval:` action polls the Marquee API and parses
   the response into globals
3. If `playing: true` → switches to marquee_page
4. If `playing: false` → switches back to dashboard_page
5. No manual intervention needed

---

## Example 4: Persistent Widget (Sidebar)

**File**: `widget_sidebar.yaml`

Marquee info lives in a 30% sidebar on the right. Dashboard takes up left 70%.

```yaml
esphome:
  name: marquee-display
  platform: esp32
  board: esp-wrover-kit

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
ota:
  password: !secret ota_password

logger:
  level: INFO

spi:
  clk_pin: GPIO18
  mosi_pin: GPIO23
  miso_pin: GPIO19

display:
  - platform: ili9341
    id: my_display
    cs_pin: GPIO15
    dc_pin: GPIO2
    reset_pin: GPIO4
    rotation: 1
    data_rate: 40MHz
    pages:
      - id: main_page
        lambda: |-
          // Reads globals populated by the interval: action below —
          // NOT a text_sensor (see ESPHOME_CONFIG.md, "Why not a text_sensor?")

          // Left side: Dashboard (70% of width = 224px)
          it.printf(10, 10, id(large_font), COLOR_WHITE, "Dashboard");
          it.printf(10, 50, id(small_font), COLOR_GRAY, "Time: 14:32");
          it.printf(10, 70, id(small_font), COLOR_GRAY, "Temp: 72°F");
          it.printf(10, 90, id(small_font), COLOR_GRAY, "Humidity: 45%");

          // Vertical line separator
          it.vertical_line(224, 0, 240, COLOR_GRAY);

          // Right side: Marquee widget (30% of width = 96px)
          if (id(np_playing)) {
            it.printf(230, 10, id(small_font), COLOR_YELLOW, "PLAYING");

            // Title (truncated to fit sidebar)
            std::string title = id(np_title);
            if (title.length() > 20) title = title.substr(0, 17) + "...";
            it.printf(230, 40, id(small_font), COLOR_WHITE, "%s", title.c_str());

            // Progress percentage
            if (id(np_duration_ms) > 0) {
              float pct = (float)id(np_offset_ms) / id(np_duration_ms);
              it.printf(230, 80, id(small_font), COLOR_CYAN, "%d%% play", (int)(pct*100));
            }
          } else {
            it.printf(230, 40, id(small_font), COLOR_GRAY, "No content");
            it.printf(230, 60, id(small_font), COLOR_GRAY, "playing");
          }

font:
  - file: "gfonts://Roboto"
    id: large_font
    size: 32
  - file: "gfonts://Roboto"
    id: small_font
    size: 14

# Globals hold the fields parsed out of the JSON response. A text_sensor
# would truncate at ~255 bytes, so we never store the raw JSON in one.
globals:
  - id: np_playing
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: np_title
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
          url: "http://192.168.1.10:8084/api/now-playing.json"  # CHANGE THIS
          capture_response: true
          on_response:
            then:
              - lambda: |-
                  if (response->status_code == 200) {
                    json::parse_json(body, [](JsonObject root) -> bool {
                      id(np_playing) = root["playing"] | false;
                      id(np_title)   = root["title"]   | std::string("");

                      if (root["progress"].is<JsonObject>()) {
                        id(np_offset_ms)   = root["progress"]["offsetMs"]   | 0;
                        id(np_duration_ms) = root["progress"]["durationMs"] | 0;
                      } else {
                        id(np_offset_ms) = 0;
                        id(np_duration_ms) = 0;
                      }
                      return true;
                    });
                  }
              - component.update: my_display
```

**Layout:**
```
┌─────────────────────────────────────────────┐
│                │                            │
│  Dashboard    │  Marquee Widget             │
│               │  PLAYING                    │
│  Time: 14:32  │  Movie Title                │
│  Temp: 72°F   │  45% play                   │
│               │                            │
│  (70% width)  │  (30% width)               │
└─────────────────────────────────────────────┘
```

---

## Using These Examples

### Step 1: Choose Your Example
Pick the one that matches your needs:
- **Basic**: Just show Marquee card
- **Brightness**: Control backlight
- **Interrupt**: Dashboard + Marquee
- **Widget**: Always-on sidebar

### Step 2: Copy the YAML
Copy the entire config block.

### Step 3: Customize
Change these values:
- `ssid` and `password` → your WiFi (or use `secrets.yaml`)
- `resource` URL → your Marquee server IP:port
- `cs_pin`, `dc_pin`, etc. → match your GPIO wiring
- `rotation` → test 0-3 to get orientation right

### Step 4: Upload
```bash
esphome run example.yaml
```

Or via web.esphome.io.

### Step 5: Play Content
Start playing something in Plex/Emby. Device should update within 5 seconds.

---

## Tips

- **Font sizes**: Adjust `size:` in font definitions
- **Colors**: Use COLOR_WHITE, COLOR_BLACK, COLOR_RED, COLOR_YELLOW, COLOR_CYAN, COLOR_GRAY, etc.
- **Positioning**: `it.printf(x, y, font, color, "format", args)` where x=left, y=top
- **Performance**: Keep lambdas simple; complex rendering may cause lag
- **Testing**: Use serial monitor to debug lambda code

---

## Next Steps

✅ You have a working configuration  
🎯 **Want to customize further?** Edit the lambda code  
🎯 **Having issues?** See ESPHOME_TROUBLESHOOTING.md  
🎯 **Ready for Home Assistant?** See ADVANCED/HOMEASSISTANT_INTEGRATION.md  
