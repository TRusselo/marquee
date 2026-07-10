# ESPHome Hardware Setup

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

Step-by-step guide to wire and prepare your ESP32 + display for Marquee.

## Hardware Requirements

### Minimum Setup
- **ESP32 microcontroller** (~$10)
  - ESP32-WROOM-32 (most common)
  - ESP32-S3 (newer, faster, recommended)
  - Or any ESP32 dev board
- **USB cable** (for programming)
- **WiFi network** (2.4GHz)

### Recommended Display Setup
- **ILI9341 2.8" TFT Display** (~$15-20)
  - 320x240 resolution
  - SPI interface (fast)
  - Touch support (optional)
  - Good balance of size and price
- **Breadboard and jumper wires** (for prototyping)
- **5V power supply** (optional, if not powering via USB)

### Other Display Options
ESPHome supports:
- **ST7789** (similar to ILI9341, slightly cheaper)
- **ST7735** (small, 128x160)
- **SSD1306** (0.96" OLED, monochrome, small)
- **Other SPI/I2C displays** (check ESPHome docs)

**Recommendation**: **ILI9341 is best**. Good size, common, cheap, fast, and well-supported.

---

## Wiring: ILI9341 to ESP32-WROOM-32

### Pin Mapping

```
ILI9341 Display Pins          ESP32-WROOM-32 GPIO
────────────────────────────────────────────────────────
VCC (Power)            →      5V or 3.3V (see below)
GND (Ground)           →      GND
CS (Chip Select)       →      GPIO 15
RESET                  →      GPIO 4
DC (Data/Command)      →      GPIO 2
SDI (MOSI)             →      GPIO 23
SCK (Clock)            →      GPIO 18
LED (Backlight)        →      GPIO 12 (PWM for brightness)
SDO (MISO)             →      GPIO 19 (optional, for reading)
```

### Touch Support (Optional)

If your ILI9341 has touch:
```
Touch Controller Pins          ESP32 GPIO
────────────────────────────────────────────
T_CLK                  →      GPIO 18 (shared with display clock)
T_CS                   →      GPIO 14
T_DIN                  →      GPIO 23 (shared with MOSI)
T_DO                   →      GPIO 19 (shared with MISO)
T_IRQ                  →      GPIO 27
```

### Power Considerations

**ILI9341 voltage:**
- Logic levels: 3.3V
- Power: Can accept 3.3V or 5V
- Some boards have built-in voltage regulators

**Recommendation**: Power from **3.3V pin** on ESP32 (simpler, no regulators needed). If that's insufficient, use external 5V with voltage dividers.

---

## Breadboard Wiring Diagram

```
                    ┌─────────────────────────┐
                    │  ILI9341 Display        │
                    │                         │
                    │ VCC  GND  CS   RST  DC  │
                    │  │    │    │    │    │  │
    ┌───────────────┼──┼────┼────┼────┼────┼──┬─────┐
    │               │  │    │    │    │    │  │     │
    │ ┌─────────────┴──┴────┼────┼────┼────┼──┼─────┤ ← Breadboard
    │ │                     │    │    │    │  │     │
    │ │  [Row with GPIOs]   │    │    │    │  │     │
    │ │                     │    │    │    │  │     │
    │ └─────────────┬───────┼────┼────┼────┼──┼─────┤
    │               │       │    │    │    │  │     │
    │      ┌────────┘   ┌───┘    │    │    │  │     │
    │      │      ┌─────┘   ┌────┘    │    │  │     │
    │      │      │    ┌────┘    ┌────┘    │  │     │
  ┌─┴──┬───┴──┬───┴────┼───┬─────┴────┬────┴──┴─┐   │
  │ 3V │ GND  │ GPIO 4 │15 │ GPIO 2   │ GPIO 23│   │
  │    │      │        │   │          │        │   │
  └────┴──────┴────────┴───┴──────────┴────────┘   │
  ESP32-WROOM-32 Board                             │
                                                   │
  [USB Connection to Computer for Programming] ←──┘
```

### Connection Checklist

- [ ] ILI9341 VCC → ESP32 3.3V (or 5V through regulator)
- [ ] ILI9341 GND → ESP32 GND
- [ ] ILI9341 CS → GPIO 15
- [ ] ILI9341 RST → GPIO 4
- [ ] ILI9341 DC → GPIO 2
- [ ] ILI9341 SDI (MOSI) → GPIO 23
- [ ] ILI9341 SCK → GPIO 18
- [ ] ILI9341 LED (backlight) → GPIO 12
- [ ] ESP32 USB → Computer (for initial programming)

---

## Installation Methods

### Method 1: ESPHome Web (Easiest) ⭐ RECOMMENDED

1. **Go to**: https://web.esphome.io
2. **Connect ESP32** via USB cable to computer
3. **Click "CONNECT"** and select your ESP32 device
4. **Create a new device**:
   - Name: "marquee-display"
   - Device type: "Generic ESP32"
5. **Download the YAML template**
6. **Edit the YAML** (see ESPHOME_CONFIG.md)
7. **Upload**: Paste YAML into web interface → "Install"
8. **Done!** Your device is now wireless

**Pros**: No software installation, works in browser  
**Cons**: First flash only via USB; subsequent updates are wireless

---

### Method 2: Arduino IDE

#### 2.1 Install Arduino IDE
1. Download [Arduino IDE 2.0+](https://www.arduino.cc/en/software)
2. Open Arduino IDE
3. Go to **File → Preferences**
4. Add to **Additional Boards Manager URLs**:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
5. Click **OK**

#### 2.2 Install ESP32 Board Support
1. Go to **Tools → Board → Boards Manager**
2. Search for "esp32"
3. Install **esp32** by Espressif Systems (latest version)

#### 2.3 Select Your Board
1. **Tools → Board → ESP32 → "ESP32 Dev Module"**
2. **Tools → Port → COM3** (or your USB port)
3. **Tools → Upload Speed → 115200**

#### 2.4 Install Libraries
Go to **Tools → Manage Libraries** and install:
- **TFT_eSPI** by Bodmer
- **ArduinoJson** by Benoit Blanchon

#### 2.5 Configure TFT_eSPI
1. Navigate to `Arduino/libraries/TFT_eSPI/`
2. Open `User_Setup.h`
3. Uncomment and verify these lines:
   ```cpp
   #define ILI9341_DRIVER
   #define TFT_CS   15   // Chip select
   #define TFT_DC   2    // Data/Command
   #define TFT_RST  4    // Reset
   #define TFT_MOSI 23   // MOSI
   #define TFT_SCLK 18   // Clock
   #define TFT_MISO 19   // MISO
   #define TFT_BL   12   // Backlight
   #define SPI_FREQUENCY 40000000
   ```

#### 2.6 Upload Custom Firmware
1. Open `esp32/marquee_display.ino` (from the Marquee repo)
2. **Edit WiFi credentials** (lines ~20):
   ```cpp
   const char *WIFI_SSID = "YOUR_SSID";
   const char *WIFI_PASSWORD = "YOUR_PASSWORD";
   ```
3. Click **Upload** (Ctrl+U)
4. Wait for compile and upload (~2 minutes)
5. Open **Tools → Serial Monitor** (Ctrl+Shift+M)
6. Set baud to **115200**
7. Look for output:
   ```
   Marquee Display Firmware
   Initializing...
   Connecting to WiFi: YOUR_SSID
   WiFi connected
   IP address: 192.168.1.100
   Setup complete. Ready for display.
   ```

**Pros**: Full control, can modify code  
**Cons**: More setup, requires code editing

---

### Method 3: PlatformIO (VS Code)

#### 3.1 Install PlatformIO
1. Install [VS Code](https://code.visualstudio.com/)
2. Go to **Extensions** (Ctrl+Shift+X)
3. Search for "PlatformIO"
4. Install **PlatformIO IDE**
5. Reload VS Code

#### 3.2 Create New Project
1. Click **PlatformIO Home**
2. **New Project**
3. Name: "marquee-display"
4. Board: "Espressif ESP32 Dev Module"
5. Framework: "Arduino"
6. Location: Choose your folder

#### 3.3 Follow Arduino IDE Steps
- Same library installation
- Same TFT_eSPI config
- Same firmware upload

**Pros**: Professional IDE, better code editing  
**Cons**: More setup than web method

---

## Verify Hardware

### Test 1: Check USB Connection
```bash
# List connected devices (Mac/Linux)
ls -la /dev/tty.usb*

# Windows: Check Device Manager for COM port
```

### Test 2: Verify Display Connection
1. Flash a **test sketch** (TFT_eSPI examples)
2. In Arduino IDE: **File → Examples → TFT_eSPI → 160 Test → Test_Rotation_Buttons**
3. Modify GPIO pins to match your wiring
4. Upload and watch serial monitor
5. Display should show colorful test pattern

### Test 3: Check GPIO Pins
```python
# Quick Python test (on your computer, not ESP32)
# Just to verify pin numbers

pin_map = {
    "VCC": "3.3V or 5V",
    "GND": "GND",
    "CS": 15,
    "RST": 4,
    "DC": 2,
    "MOSI": 23,
    "SCK": 18,
    "LED": 12,
}

for pin, value in pin_map.items():
    print(f"{pin}: GPIO {value}")
```

---

## Troubleshooting

### Display shows nothing
**Possible causes:**
1. Wiring is incorrect
2. GPIO pins don't match config
3. Display is unpowered
4. SPI frequency too high

**Fix:**
- Double-check wiring against pin map
- Verify GPIO assignments in code/config
- Test with simple TFT_eSPI example first
- Try lower SPI frequency (20MHz instead of 40MHz)

### Display shows garbage/corrupted
**Possible causes:**
1. SPI clock too fast
2. Power supply unstable
3. Loose wire connection

**Fix:**
- Reduce SPI frequency in TFT_eSPI User_Setup.h
- Use stable 5V power supply
- Re-seat all breadboard wires
- Add capacitors (100µF) between power pins

### USB device not recognized
**Possible causes:**
1. USB driver not installed (Windows)
2. Wrong USB cable (data cable, not charging-only)
3. ESP32 board not in bootloader mode

**Fix:**
- Install [CH340 drivers](https://sparks.gogo.co.nz/ch340.html) (Windows)
- Try different USB cable
- Try different USB port
- Hold BOOT button while plugging in (for some boards)

### Can't upload firmware
**Possible causes:**
1. COM port incorrect
2. Baud rate wrong
3. Board selection wrong

**Fix:**
- Verify **Tools → Port** shows your device
- Set **Tools → Upload Speed → 115200**
- Select **Tools → Board → ESP32 Dev Module**
- Try uploading again

---

## Next Steps

✅ Hardware is wired and tested  
✅ ESP32 is programmed (custom firmware or ESPHome)  
✅ Display shows something (even just a test pattern)

👉 **Now configure ESPHome:** Go to [ESPHOME_CONFIG.md](ESPHOME_CONFIG.md)

👉 **Or use custom firmware:** See [CUSTOM_FIRMWARE/REFERENCE_IMPLEMENTATION.md](../../CUSTOM_FIRMWARE/REFERENCE_IMPLEMENTATION.md)
