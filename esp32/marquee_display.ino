/**
 * Marquee Display Firmware for ESP32
 *
 * Reference implementation for rendering Marquee card on an ESP32-based display.
 * Communicates with Marquee service via HTTP.
 *
 * Requirements:
 * - ESP32 development board
 * - ILI9341 2.8" touchscreen display (or compatible SPI display)
 * - TFT_eSPI library (configure for your display in User_Setup.h)
 * - AsyncTCP + ESPAsyncWebServer for HTTP server
 * - ArduinoJson 7 + ESP32 core 3.x
 *
 * Features:
 * - Polls Marquee server for now-playing.json URL
 * - Fetches now-playing.json via HTTP and parses it directly
 * - Renders key fields (title, subtitle, year, summary, progress)
 * - REST API for remote control (brightness, stop, etc.)
 * - Graceful idle/sleep handling
 */

#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <TFT_eSPI.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>

// WiFi credentials
const char *WIFI_SSID = "YOUR_SSID";
const char *WIFI_PASSWORD = "YOUR_PASSWORD";

// Display configuration
TFT_eSPI tft = TFT_eSPI();
const int DISPLAY_WIDTH = 320;
const int DISPLAY_HEIGHT = 240;
const int BRIGHTNESS_PIN = 12; // GPIO pin for backlight PWM
const int MAX_BRIGHTNESS = 255;

// Service state
AsyncWebServer server(80);
String current_card_url = "";
unsigned long last_fetch_time = 0;
unsigned long last_activity_time = 0;
const unsigned long FETCH_INTERVAL = 5000; // Fetch card every 5s
const unsigned long IDLE_TIMEOUT = 300000; // 5 minutes of inactivity
int current_brightness_pct = 78;   // 0-100 (the user's chosen level)
const int IDLE_BRIGHTNESS_PCT = 20; // dim level while idle (does not overwrite the above)
bool is_displaying = false;
bool is_idle = false;     // stopped: dimmed AND showing the idle screen
bool is_dimmed = false;   // playing but idle-timed-out: dimmed, still showing the card

// Forward declarations
void setup_wifi();
void setup_display();
void setup_web_server();
void fetch_and_render_card();
void render_loading_screen();
void render_idle_screen();
void handle_display_request(AsyncWebServerRequest *request, JsonVariant &json);
void handle_stop_request(AsyncWebServerRequest *request, JsonVariant &json);
void handle_brightness_request(AsyncWebServerRequest *request, JsonVariant &json);
void set_brightness(int level);
void go_idle();
void go_dim();
void wake_up();

void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println("\n\nMarquee Display Firmware");
  Serial.println("Initializing...");
  
  setup_display();
  setup_wifi();
  setup_web_server();
  
  Serial.println("Setup complete. Ready for display.");
  render_idle_screen();
}

void loop() {
  unsigned long now = millis();
  
  // After inactivity: if a title is still playing, dim the card (cinema mode)
  // so it isn't a distraction; only drop to the idle screen once playback stops.
  if (!is_idle && !is_dimmed && (now - last_activity_time > IDLE_TIMEOUT)) {
    if (is_displaying) {
      go_dim();
    } else {
      go_idle();
    }
  }
  
  // Fetch and render card at interval
  if (is_displaying && (now - last_fetch_time > FETCH_INTERVAL)) {
    fetch_and_render_card();
    last_fetch_time = now;
  }
  
  delay(100);
}

void setup_display() {
  // Initialize TFT display
  tft.init();
  tft.setRotation(1); // Landscape
  tft.fillScreen(TFT_BLACK);
  
  // Setup brightness PWM
  ledcAttach(BRIGHTNESS_PIN, 5000, 8);   // pin, freq, resolution (core 3.x)
  set_brightness(current_brightness_pct);
}

void setup_wifi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed to connect to WiFi");
  }
}

void setup_web_server() {
  // Status endpoint
  server.on("/status", HTTP_GET, [](AsyncWebServerRequest *request) {
    JsonDocument doc;
    doc["status"] = "ok";
    doc["uptime_seconds"] = millis() / 1000;
    doc["displaying"] = is_displaying;
    doc["brightness"] = current_brightness_pct;
    
    String response;
    serializeJson(doc, response);
    request->send(200, "application/json", response);
  });
  
  // Info endpoint
  server.on("/info", HTTP_GET, [](AsyncWebServerRequest *request) {
    JsonDocument doc;
    doc["name"] = "Marquee Display";
    doc["firmware_version"] = "1.0.0";
    doc["model"] = "ESP32 ILI9341";
    doc["uptime_seconds"] = millis() / 1000;
    
    String response;
    serializeJson(doc, response);
    request->send(200, "application/json", response);
  });
  
  // Display endpoint: POST {"json_url": "http://..."}
  server.onJson("/display", HTTP_POST, [](AsyncWebServerRequest *request, JsonVariant &json) {
    handle_display_request(request, json);
  });
  
  // Stop endpoint: POST {}
  server.onJson("/stop", HTTP_POST, [](AsyncWebServerRequest *request, JsonVariant &json) {
    handle_stop_request(request, json);
  });
  
  // Brightness endpoint: POST {"level": 0-100}
  server.onJson("/brightness", HTTP_POST, [](AsyncWebServerRequest *request, JsonVariant &json) {
    handle_brightness_request(request, json);
  });
  
  server.begin();
  Serial.println("Web server started");
}

void handle_display_request(AsyncWebServerRequest *request, JsonVariant &json) {
  if (!json.is<JsonObject>()) {
    request->send(400, "application/json", R"({"error":"invalid json"})");
    return;
  }
  
  String url = json["json_url"].as<String>();
  if (url.isEmpty()) {
    request->send(400, "application/json", R"({"error":"missing json_url"})");
    return;
  }
  current_card_url = url;   // now points at now-playing.json
  wake_up();
  is_displaying = true;
  last_activity_time = millis();
  render_loading_screen();
  fetch_and_render_card();
  
  JsonDocument doc;
  doc["ok"] = true;
  String response;
  serializeJson(doc, response);
  request->send(200, "application/json", response);
}

void handle_stop_request(AsyncWebServerRequest *request, JsonVariant &json) {
  is_displaying = false;
  current_card_url = "";
  go_idle();
  
  JsonDocument doc;
  doc["ok"] = true;
  String response;
  serializeJson(doc, response);
  request->send(200, "application/json", response);
}

void handle_brightness_request(AsyncWebServerRequest *request, JsonVariant &json) {
  if (!json.is<JsonObject>()) {
    request->send(400, "application/json", R"({"error":"invalid json"})");
    return;
  }
  
  int level = json["level"].as<int>();
  set_brightness(constrain(level, 0, 100));
  
  JsonDocument doc;
  doc["ok"] = true;
  doc["brightness"] = current_brightness_pct;
  String response;
  serializeJson(doc, response);
  request->send(200, "application/json", response);
}

void set_brightness(int percent) {
  current_brightness_pct = constrain(percent, 0, 100);
  ledcWrite(BRIGHTNESS_PIN, map(current_brightness_pct, 0, 100, 0, MAX_BRIGHTNESS));
  Serial.printf("Brightness: %d%%\n", current_brightness_pct);
}

void render_loading_screen() {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("Loading...", DISPLAY_WIDTH / 2 - 40, DISPLAY_HEIGHT / 2 - 12);
}

void render_idle_screen() {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.setTextSize(2);
  int x = (DISPLAY_WIDTH - tft.textWidth("Marquee Ready")) / 2;
  int y = (DISPLAY_HEIGHT - 16) / 2;
  tft.drawString("Marquee Ready", x, y);
  
  // Draw IP address at bottom
  String ip = WiFi.localIP().toString();
  tft.setTextSize(1);
  tft.drawString(ip, 10, DISPLAY_HEIGHT - 16);
}

void fetch_and_render_card() {
  if (current_card_url.isEmpty()) {
    return;
  }
  
  HTTPClient http;
  http.begin(current_card_url);
  int httpCode = http.GET();
  
  if (httpCode != 200) {
    Serial.print("Failed to fetch card: HTTP ");
    Serial.println(httpCode);
    render_loading_screen();
    http.end();
    return;
  }
  
  String body = http.getString();
  http.end();

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, body);
  if (error) {
    Serial.print("JSON parse error: ");
    Serial.println(error.c_str());
    render_loading_screen();
    return;
  }
  if (!doc["playing"].as<bool>()) {
    go_idle();
    return;
  }

  // Simple rendering
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  
  String title = doc["title"].as<String>();
  if (title.length() > 0) {
    // Wrap long titles
    if (title.length() > 20) {
      tft.drawString(title.substring(0, 20), 10, 10);
      tft.drawString(title.substring(20), 10, 30);
    } else {
      tft.drawString(title, 10, 10);
    }
  }
  
  // Show additional info
  tft.setTextSize(1);
  tft.setTextColor(TFT_LIGHTGREY);
  
  String subtitle = doc["subtitle"].as<String>();
  if (subtitle.length() > 0) {
    tft.drawString(subtitle, 10, 50);
  }
  
  String year = doc["year"].as<String>();
  if (year.length() > 0) {
    tft.drawString(year, 10, 70);
  }
  
  String summary = doc["summary"].as<String>();
  if (summary.length() > 0) {
    // Truncate and wrap summary
    if (summary.length() > 80) summary = summary.substring(0, 80) + "...";
    tft.drawString(summary, 10, 100);
  }
  
  // Show progress bar if available
  if (doc["progress"].is<JsonObject>()) {
    int offsetMs = doc["progress"]["offsetMs"];
    int durationMs = doc["progress"]["durationMs"];
    if (durationMs > 0) {
      int progress_percent = (offsetMs * 100) / durationMs;
      int bar_width = (DISPLAY_WIDTH - 20) * progress_percent / 100;
      tft.fillRect(10, 200, bar_width, 10, TFT_GREEN);
      tft.drawRect(10, 200, DISPLAY_WIDTH - 20, 10, TFT_WHITE);
    }
  }
}

void go_idle() {
  is_idle = true;
  is_dimmed = false;
  // Dim the backlight directly, WITHOUT clobbering current_brightness_pct,
  // so wake_up() can restore the user's chosen level.
  ledcWrite(BRIGHTNESS_PIN, map(IDLE_BRIGHTNESS_PCT, 0, 100, 0, MAX_BRIGHTNESS));
  render_idle_screen();
  Serial.println("Display idle");
}

// Cinema mode: still playing, but idle-timed-out. Dim the backlight but KEEP
// rendering the card (the fetch loop repaints it at this reduced brightness).
// Does not overwrite current_brightness_pct, so a new title restores full level.
void go_dim() {
  is_dimmed = true;
  ledcWrite(BRIGHTNESS_PIN, map(IDLE_BRIGHTNESS_PCT, 0, 100, 0, MAX_BRIGHTNESS));
  Serial.println("Display dimmed (still playing)");
}

void wake_up() {
  is_idle = false;
  is_dimmed = false;
  set_brightness(current_brightness_pct);
  Serial.println("Display active");
}
