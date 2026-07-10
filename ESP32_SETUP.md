# ESP32 Setup Guide

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

Detailed instructions for setting up and configuring an ESP32 microcontroller to display Marquee cards.

## Hardware Requirements

### Minimum
- **ESP32 Development Board** (e.g., ESP32-WROOM-32, ESP32-S3)
- **USB cable** (for programming)
- **WiFi network** on the same LAN as Marquee server

### Recommended (For Display)
- **ILI9341 2.8" SPI TFT Display** (~$15-20)
  - 320x240 resolution
  - SPI interface
  - Touch support (optional)
- **Breadboard and jumper wires**
- **5V power supply** (if not powering via USB)

## Wiring (ILI9341 to ESP32)

```
ILI9341 Display          ESP32 WROOM-32
─────────────────────────────────────────
VCC (5V)           →     5V (or 3.3V via regulator)
GND                →     GND
CS (Chip Select)   →     GPIO 15 (or GPIO 5)
RESET              →     GPIO 4
DC (Data/Command)  →     GPIO 2
SDI (MOSI)         →     GPIO 23
SCK (Clock)        →     GPIO 18
LED (Backlight)    →     GPIO 12 (PWM for brightness)
SDO (MISO)         →     GPIO 19 (optional)
T_CLK              →     GPIO 18 (touch, optional)
T_CS               →     GPIO 14 (touch, optional)
T_DIN              →     GPIO 23 (touch, optional)
T_DO               →     GPIO 19 (touch, optional)
T_IRQ              →     GPIO 27 (touch, optional)
```

**Note**: Exact GPIO assignments depend on your board. ILI9341 displays are typically 5V-tolerant but run on 3.3V signals. Some boards include voltage regulators.

## Software Setup

### 1. Install Arduino IDE or PlatformIO

#### Option A: Arduino IDE (Recommended for beginners)

1. Download [Arduino IDE 2.0+](https://www.arduino.cc/en/software)
2. Open Arduino IDE
3. Go to **File → Preferences**
4. Add to **Additional Boards Manager URLs**:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
5. Go to **Tools → Board → Boards Manager**
6. Search for "esp32" and install the latest version
7. Select **Tools → Board → ESP32 → "ESP32 Dev Module"** (or your variant)
8. Select the correct **COM port** under **Tools → Port**

#### Option B: PlatformIO (VSCode)

1. Install [PlatformIO extension](https://platformio.org/install/ide?install=vscode) in VSCode
2. Create new project: **PlatformIO: New Project**
3. Board: **Espressif ESP32 Dev Module**
4. Framework: **Arduino**

### 2. Install Required Libraries

In Arduino IDE, go to **Tools → Manage Libraries** and install:

- **TFT_eSPI** by Bodmer
  - Essential for ILI9341 display
  - After install, navigate to `Arduino/libraries/TFT_eSPI/`
  - Open `User_Setup.h` and uncomment:
    ```cpp
    #define ILI9341_DRIVER
    #define TFT_CS   15   // Chip select
    #define TFT_DC   2    // Data/Command
    #define TFT_RST  4    // Reset
    #define TFT_MOSI 23   // MOSI
    #define TFT_SCLK 18   // Clock
    #define TFT_MISO 19   // MISO (optional)
    #define TFT_BL   12   // Backlight
    #define SPI_FREQUENCY 40000000
    ```

- **ArduinoJson** by Benoit Blanchon
  - For JSON parsing

- **AsyncTCP** by Me-No-Dev
  - For async HTTP server

- **ESPAsyncWebServer** by Me-No-Dev
  - For REST API endpoints

### 3. Configure Firmware

1. Download or copy `esp32/marquee_display.ino` from the branch
2. Open in Arduino IDE
3. **Modify these lines** for your setup:

   ```cpp
   // WiFi credentials (line ~20)
   const char *WIFI_SSID = "YOUR_SSID";
   const char *WIFI_PASSWORD = "YOUR_PASSWORD";
   
   // GPIO pins (match your wiring)
   const int BRIGHTNESS_PIN = 12;  // Backlight PWM
   ```

4. **Optional: Configure display rotation**
   ```cpp
   tft.setRotation(1);  // 0=portrait, 1=landscape, 2=inverted portrait, 3=inverted landscape
   ```

### 4. Upload Firmware

1. Connect ESP32 to computer via USB
2. In Arduino IDE: **Sketch → Upload** (or Ctrl+U)
3. Wait for upload to complete (~30 seconds)
4. Open **Tools → Serial Monitor** (or PlatformIO: **PlatformIO → Serial Monitor**)
5. Set baud rate to **115200**
6. Watch for output:
   ```
   Marquee Display Firmware
   Initializing...
   Setup complete. Ready for display.
   ```

### 5. Find ESP32 IP Address

In Serial Monitor, look for:
```
Connecting to WiFi: YOUR_SSID
WiFi connected
IP address: 192.168.1.100
```

Note the IP address for Marquee configuration.

## Marquee Server Configuration

### Update compose.yaml

```yaml
services:
  marquee:
    build: .
    image: marquee:local
    network_mode: host
    restart: unless-stopped
    environment:
      # Plex (or Emby)
      BACKEND_TYPE: plex
      BACKEND_HOST: http://localhost:32400
      BACKEND_TOKEN: your-plex-token
      
      # ESP32 display
      DEVICE_TYPE: esp32
      DEVICE_ADDRESS: 192.168.1.100    # ESP32 IP from step 5
      DEVICE_PORT: 80
      
      # Service
      PAGE_URL: http://192.168.1.10:8084/image
      POLL_SECONDS: 5
    volumes:
      - ./data:/config
```

Then:
```bash
docker compose up -d --build
docker compose logs -f marquee
```

## Testing

### 1. Verify Connectivity

```bash
curl http://192.168.1.100/status
```

Expected response:
```json
{"status":"ok","uptime_seconds":123,"displaying":false,"brightness":200}
```

### 2. Fetch Device Info

```bash
curl http://192.168.1.100/info
```

Expected response:
```json
{"name":"Marquee Display","firmware_version":"1.0.0","model":"ESP32 ILI9341","uptime_seconds":123}
```

### 3. Send a Test Card

```bash
curl -X POST http://192.168.1.100/display \
  -H 'Content-Type: application/json' \
  -d '{"card_url": "http://192.168.1.10:8084/image"}'
```

The display should show "Loading..." then render the card.

### 4. Test Brightness

```bash
# Set to 50%
curl -X POST http://192.168.1.100/brightness \
  -H 'Content-Type: application/json' \
  -d '{"level": 50}'

# Set to 100%
curl -X POST http://192.168.1.100/brightness \
  -H 'Content-Type: application/json' \
  -d '{"level": 100}'
```

### 5. Stop Display

```bash
curl -X POST http://192.168.1.100/stop
```

### 6. Full Integration Test

1. Start Marquee server
2. Play content in Plex (or Emby)
3. Watch Serial Monitor on ESP32:
   ```
   device poll failed: ...
   playing content title -> casting
   ```
4. Display should update with content info
5. Stop playback in Plex
6. Display should return to idle screen

## Troubleshooting

### ESP32 won't connect to WiFi

- **Check SSID and password** are correct and spelled exactly
- **Verify WiFi is 2.4GHz** (ESP32 doesn't support 5GHz)
- **Check Serial Monitor** for error messages
- **Restart ESP32**: Unplug/replug USB or press RESET button

### Display shows garbage or nothing

- **Verify TFT_eSPI User_Setup.h** GPIO pins match your wiring
- **Check SPI frequency** (default 40MHz; try 20MHz if unstable)
- **Test with TFT_eSPI examples** first:
  - **File → Examples → TFT_eSPI → 160 Test → Test_Rotation_Buttons**
- **Verify backlight is powered** (should be bright without firmware)

### Marquee can't reach ESP32

- **Verify ESP32 IP** matches `DEVICE_ADDRESS` in compose.yaml
- **Check they're on same LAN/network**
- **Test connectivity**:
  ```bash
  ping 192.168.1.100
  curl http://192.168.1.100/status
  ```
- **Check Docker network mode**: Should be `host` for LAN access

### Card displays but content is cut off or wrong size

- **Adjust display rotation** in firmware (`tft.setRotation()`)
- **Modify rendering code** in `fetch_and_render_card()` function
- Check `DISPLAY_WIDTH` and `DISPLAY_HEIGHT` constants

### Brightness not responding

- **Verify GPIO 12** is connected to display backlight via PWM-capable pin
- **Check TFT_BL definition** in User_Setup.h
- **Test PWM directly**:
  ```cpp
  ledcWrite(0, 128);  // Set to 50%
  ```

## Advanced Customization

### Change Display Rotation

In `marquee_display.ino`, modify:
```cpp
void setup_display() {
  tft.init();
  tft.setRotation(3);  // 0-3, depending on desired orientation
```

### Add Touch Support

Uncomment touch pins in `User_Setup.h` and add touch handling:
```cpp
#define TOUCH_CS 14
TouchScreen ts(XP, YP, XM, YM, 300);
```

Then in `loop()`, check for touches and adjust brightness or display.

### Customize Idle Screen

Modify `render_idle_screen()` function to show custom text, clock, or weather.

### Add Image Rendering

For full card rendering:
1. Use a library like **TJpg_Decoder** for JPEG decoding
2. Fetch poster/backdrop images from Marquee server
3. Cache them locally
4. Render with proper layout and fonts

## Performance Tips

1. **SPI Frequency**: Start at 40MHz; reduce if display is glitchy
2. **Polling Interval**: Default 5s should be fine; don't go below 2s
3. **WiFi**: Ensure strong signal; consider 5GHz router nearby (for 2.4GHz strength)
4. **Memory**: ESP32 has ~520KB RAM; avoid large images or buffers

## Next Steps

- Explore TFT_eSPI examples for more rendering techniques
- Integrate touch input for manual brightness/settings adjustment
- Add NTP for accurate time display on idle screen
- Create multiple display themes/profiles
- Submit improvements back to the Marquee project!
