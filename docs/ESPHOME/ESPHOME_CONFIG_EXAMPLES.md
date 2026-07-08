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
          auto root = json::parse_json(id(marquee_json).state);
          it.fill(COLOR_BLACK);
          
          // Title
          if (root["title"].is<std::string>()) {
            it.printf(10, 20, id(large_font), COLOR_WHITE, "%s",
                     root["title"].as<std::string>().c_str());
          }
          
          // Subtitle (for episodes)
          if (root["subtitle"].is<std::string>()) {
            std::string sub = root["subtitle"].as<std::string>();
            if (!sub.empty()) {
              it.printf(10, 60, id(small_font), COLOR_GRAY, "%s", sub.c_str());
            }
          }
          
          // Progress bar
          if (root["progress"].is<object>()) {
            auto prog = root["progress"];
            if (prog["durationMs"].is<int>()) {
              int duration = prog["durationMs"];
              int offset = prog["offsetMs"];
              if (duration > 0) {
                float pct = (float)offset / duration;
                int bar_width = (int)(280 * pct);
                it.rectangle(10, 100, 280, 15);
                it.filled_rectangle(10, 100, bar_width, 15);
              }
            }
          }
          
          // Runtime
          if (root["runtime"].is<std::string>()) {
            it.printf(10, 130, id(small_font), COLOR_GRAY, "%s",
                     root["runtime"].as<std::string>().c_str());
          }
          
          // Genres
          if (root["genres"].is<array>()) {
            std::string genre_str;
            for (auto &g : root["genres"].as<array>()) {
              if (g.is<std::string>()) {
                if (!genre_str.empty()) genre_str += ", ";
                genre_str += g.as<std::string>();
              }
            }
            if (!genre_str.empty()) {
              it.printf(10, 155, id(small_font), COLOR_YELLOW, "%s", genre_str.c_str());
            }
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

http_request:
  useragent: esphome/marquee
  timeout: 10s

text_sensor:
  - platform: http_request
    name: "Marquee Card"
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json  # CHANGE THIS
    scan_interval: 5s
    on_value:
      then:
        - lambda: |-
            auto root = json::parse_json(x);
            if (root["playing"].is<bool>() && root["playing"].as<bool>()) {
              id(my_display).show_page(id(marquee_page));
            } else {
              id(my_display).show_page(id(idle_page));
            }
        - component.update: my_display
```

**How to use:**
1. Copy this YAML
2. Change `resource:` URL to your Marquee server
3. Create `secrets.yaml` with WiFi credentials
4. Upload to your ESP32
5. Done!

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
          auto root = json::parse_json(id(marquee_json).state);
          it.fill(COLOR_BLACK);
          
          // Title
          if (root["title"].is<std::string>()) {
            it.printf(10, 20, id(large_font), COLOR_WHITE, "%s",
                     root["title"].as<std::string>().c_str());
          }
          
          // Subtitle (episodes)
          if (root["subtitle"].is<std::string>()) {
            it.printf(10, 60, id(small_font), COLOR_GRAY, "%s",
                     root["subtitle"].as<std::string>().c_str());
          }
          
          // Progress bar
          if (root["progress"].is<object>()) {
            auto prog = root["progress"];
            int duration = prog["durationMs"];
            int offset = prog["offsetMs"];
            if (duration > 0) {
              float pct = (float)offset / duration;
              int bar_width = (int)(280 * pct);
              it.rectangle(10, 100, 280, 15);
              it.filled_rectangle(10, 100, bar_width, 15);
              it.printf(300, 100, id(small_font), COLOR_WHITE, "%d%%", (int)(pct*100));
            }
          }
          
          // Runtime
          if (root["runtime"].is<std::string>()) {
            it.printf(10, 130, id(small_font), COLOR_GRAY, "%s",
                     root["runtime"].as<std::string>().c_str());
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

http_request:

text_sensor:
  - platform: http_request
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json  # CHANGE THIS
    scan_interval: 5s
    on_value:
      then:
        - lambda: |-
            auto root = json::parse_json(x);
            if (root["playing"].is<bool>() && root["playing"].as<bool>()) {
              id(my_display).show_page(id(marquee_page));
            } else {
              id(my_display).show_page(id(dashboard_page));
            }
        - component.update: my_display
```

**How it works:**
1. Device shows time + weather on dashboard
2. Every 5 seconds, polls Marquee API
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
          auto root = json::parse_json(id(marquee_json).state);
          
          // Left side: Dashboard (70% of width = 224px)
          it.printf(10, 10, id(large_font), COLOR_WHITE, "Dashboard");
          it.printf(10, 50, id(small_font), COLOR_GRAY, "Time: 14:32");
          it.printf(10, 70, id(small_font), COLOR_GRAY, "Temp: 72°F");
          it.printf(10, 90, id(small_font), COLOR_GRAY, "Humidity: 45%");
          
          // Vertical line separator
          it.vertical_line(224, 0, 240, COLOR_GRAY);
          
          // Right side: Marquee widget (30% of width = 96px)
          if (root["playing"].is<bool>() && root["playing"].as<bool>()) {
            it.printf(230, 10, id(small_font), COLOR_YELLOW, "PLAYING");
            
            // Title
            if (root["title"].is<std::string>()) {
              std::string title = root["title"].as<std::string>();
              // Truncate to fit sidebar
              if (title.length() > 20) title = title.substr(0, 17) + "...";
              it.printf(230, 40, id(small_font), COLOR_WHITE, "%s", title.c_str());
            }
            
            // Progress percentage
            if (root["progress"].is<object>()) {
              auto prog = root["progress"];
              int duration = prog["durationMs"];
              int offset = prog["offsetMs"];
              if (duration > 0) {
                float pct = (float)offset / duration;
                it.printf(230, 80, id(small_font), COLOR_CYAN, "%d%% play", (int)(pct*100));
              }
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

http_request:

text_sensor:
  - platform: http_request
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json  # CHANGE THIS
    scan_interval: 5s
    on_value:
      then:
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
