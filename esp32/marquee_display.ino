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
 * 
 * Features:
 * - Polls Marquee server for card URL
 * - Fetches HTML card via HTTP
 * - Renders card using embedded browser-like engine (minimal)
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
int current_brightness = 200;
bool is_displaying = false;
bool is_idle = false;

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
  
  // Check for inactivity and go idle
  if (!is_idle && (now - last_activity_time > IDLE_TIMEOUT)) {
    go_idle();
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
  ledcSetup(0, 5000, 8); // Channel 0, 5kHz, 8-bit
  ledcAttachPin(BRIGHTNESS_PIN, 0);
  set_brightness(current_brightness);
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
    DynamicJsonDocument doc(256);
    doc["status"] = "ok";
    doc["uptime_seconds"] = millis() / 1000;
    doc["displaying"] = is_displaying;
    doc["brightness"] = current_brightness;
    
    String response;
    serializeJson(doc, response);
    request->send(200, "application/json", response);
  });
  
  // Info endpoint
  server.on("/info", HTTP_GET, [](AsyncWebServerRequest *request) {
    DynamicJsonDocument doc(256);
    doc["name"] = "Marquee Display";
    doc["firmware_version"] = "1.0.0";
    doc["model"] = "ESP32 ILI9341";
    doc["uptime_seconds"] = millis() / 1000;
    
    String response;
    serializeJson(doc, response);
    request->send(200, "application/json", response);
  });
  
  // Display endpoint: POST {"card_url": "http://..."}
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
  
  String url = json["card_url"].as<String>();
  if (url.isEmpty()) {
    request->send(400, "application/json", R"({"error":"missing card_url"})");
    return;
  }
  
  current_card_url = url;
  wake_up();
  is_displaying = true;
  last_activity_time = millis();
  
  render_loading_screen();
  fetch_and_render_card();
  
  DynamicJsonDocument doc(128);
  doc["ok"] = true;
  String response;
  serializeJson(doc, response);
  request->send(200, "application/json", response);
}

void handle_stop_request(AsyncWebServerRequest *request, JsonVariant &json) {
  is_displaying = false;
  current_card_url = "";
  go_idle();
  
  DynamicJsonDocument doc(128);
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
  
  DynamicJsonDocument doc(128);
  doc["ok"] = true;
  doc["brightness"] = current_brightness;
  String response;
  serializeJson(doc, response);
  request->send(200, "application/json", response);
}

void set_brightness(int percent) {
  current_brightness = map(constrain(percent, 0, 100), 0, 100, 0, MAX_BRIGHTNESS);
  ledcWrite(0, current_brightness);
  Serial.print("Brightness set to: ");
  Serial.print(percent);
  Serial.println("%");
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
  
  String html = http.getString();
  http.end();
  
  // Simple rendering: extract JSON from HTML, parse, display key fields
  // A real implementation would:
  // - Parse HTML/CSS
  // - Fetch images (poster, backdrop) and cache them
  // - Render with proper layout, fonts, colors
  // - Handle touch input if applicable
  
  // For now, parse the JSON embedded in the HTML and show basic info
  int jsonStart = html.indexOf("var nowPlayingData = ");
  if (jsonStart == -1) {
    render_loading_screen();
    return;
  }
  
  jsonStart += 21; // Skip "var nowPlayingData = "
  int jsonEnd = html.indexOf(";", jsonStart);
  if (jsonEnd == -1) jsonEnd = html.indexOf("}", jsonStart) + 1;
  
  String jsonStr = html.substring(jsonStart, jsonEnd);
  
  DynamicJsonDocument doc(2048);
  DeserializationError error = deserializeJson(doc, jsonStr);
  
  if (error) {
    Serial.print("JSON parse error: ");
    Serial.println(error.c_str());
    render_loading_screen();
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
  if (doc.containsKey("progress")) {
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
  set_brightness(20); // Dim the display
  render_idle_screen();
  Serial.println("Display idle");
}

void wake_up() {
  is_idle = false;
  set_brightness(current_brightness);
  Serial.println("Display active");
}
