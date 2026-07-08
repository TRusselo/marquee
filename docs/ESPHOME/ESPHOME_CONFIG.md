# ESPHome Configuration for Marquee

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

# HTTP client to fetch Marquee JSON
http_request:
  useragent: esphome/marquee
  timeout: 10s

# Text sensor to store Marquee JSON
text_sensor:
  - platform: http_request
    name: "Marquee Card"
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json
    scan_interval: 5s
    on_value:
      then:
        # When JSON is fetched, update display
        - lambda: |-
            auto root = json::parse_json(x);
            if (root["playing"].is<bool>() && root["playing"].as<bool>()) {
              id(my_display).show_page(id(marquee_page));
            } else {
              id(my_display).show_page(id(idle_page));
            }
        - component.update: my_display
```

### Key Variables

Replace these with your values:

| Variable | Example | Notes |
|----------|---------|-------|
| `name` | `marquee-display` | Device name (no spaces) |
| `wifi_ssid` | `MY_WIFI` | Put in `secrets.yaml` |
| `wifi_password` | `password123` | Put in `secrets.yaml` |
| `resource` | `http://192.168.1.10:8084/api/now-playing.json` | Your Marquee server URL |
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
- `resource` URL — point to your Marquee server

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
   [D][text_sensor:016]: 'Marquee Card': Publish state with type='text'
   ```
3. Play something in Plex/Emby
4. Display should update within 5 seconds

---

## Rendering the Card (Lambda)

The `lambda` code in each page is where you draw to the display.

### Basic Example: Display Title

```yaml
text_sensor:
  - platform: http_request
    name: "Marquee Card"
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json
    scan_interval: 5s
    on_value:
      then:
        - component.update: my_display

display:
  - platform: ili9341
    id: my_display
    # ... other config ...
    pages:
      - id: marquee_page
        lambda: |-
          auto root = json::parse_json(id(marquee_json).state);
          
          // Clear screen
          it.fill(COLOR_BLACK);
          
          // Draw title
          if (root["title"].is<std::string>()) {
            std::string title = root["title"];
            it.printf(10, 10, id(my_font), COLOR_WHITE, "%s", title.c_str());
          }
```

### Complete Example: Title + Progress

```yaml
display:
  - platform: ili9341
    id: my_display
    # ... config ...
    pages:
      - id: marquee_page
        lambda: |-
          auto root = json::parse_json(id(marquee_json).state);
          
          // Fill background
          it.fill(COLOR_BLACK);
          
          // Title
          if (root["title"].is<std::string>()) {
            it.printf(10, 20, id(large_font), COLOR_WHITE, "%s", 
                     root["title"].as<std::string>().c_str());
          }
          
          // Runtime
          if (root["runtime"].is<std::string>()) {
            it.printf(10, 60, id(small_font), COLOR_GRAY,"%s",
                     root["runtime"].as<std::string>().c_str());
          }
          
          // Progress bar
          if (root["progress"].is<object>()) {
            int offset = root["progress"]["offsetMs"];
            int duration = root["progress"]["durationMs"];
            if (duration > 0) {
              float percent = (float)offset / duration;
              int bar_width = (int)(300 * percent);  // 300px total
              it.rectangle(10, 100, 300, 20);         // Outline
              it.filled_rectangle(10, 100, bar_width, 20);  // Fill
              
              // Percentage text
              it.printf(310, 100, id(small_font), COLOR_WHITE,
                       "%d%%", (int)(percent * 100));
            }
          }
          
          // Genres
          if (root["genres"].is<array>()) {
            std::string genres;
            for (auto &genre : root["genres"].as<array>()) {
              if (genre.is<std::string>()) {
                if (!genres.empty()) genres += ", ";
                genres += genre.as<std::string>();
              }
            }
            it.printf(10, 130, id(small_font), COLOR_YELLOW, "%s", genres.c_str());
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

Show Marquee card when playing, idle screen when not.

```yaml
text_sensor:
  - platform: http_request
    id: marquee_json
    resource: http://192.168.1.10:8084/api/now-playing.json
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

---

### Strategy 2: Persistent Widget (For larger displays)

Marquee lives in corner, other content fills rest.

```yaml
display:
  - platform: ili9341
    id: my_display
    pages:
      - id: marquee_widget
        lambda: |-
          auto root = json::parse_json(id(marquee_json).state);
          
          // Draw main dashboard on left 70%
          it.rectangle(0, 0, 224, 240);  // 70% of 320
          it.printf(10, 10, id(my_font), COLOR_WHITE, "Dashboard");
          
          // Draw Marquee widget on right 30%
          it.rectangle(224, 0, 96, 240);  // 30% of 320
          
          if (root["playing"].is<bool>() && root["playing"].as<bool>()) {
            if (root["title"].is<std::string>()) {
              it.printf(230, 10, id(small_font), COLOR_YELLOW,
                       "%s", root["title"].as<std::string>().c_str());
            }
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
- Print the raw response to serial
- Verify API is returning valid JSON
- Check field names match your lambda code

**Display doesn't update**
- Check `scan_interval` (default 5s)
- Verify `on_value` lambda is being called (add debug print)
- Check display is rendering (try simple test first)

### Add Debug Logging

```yaml
logger:
  level: DEBUG
  logs:
    http_request: DEBUG
    text_sensor: DEBUG

text_sensor:
  - platform: http_request
    id: marquee_json
    on_value:
      then:
        - logger.log:
            format: "Marquee JSON: %s"
            args: ['x.c_str()']
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
