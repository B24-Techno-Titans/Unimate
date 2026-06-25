#include <WiFi.h>
#include "esp_wifi.h"
#include "esp_bt.h"
#include <WebServer.h>
#include <ESPmDNS.h>
#include <math.h>
#include <Adafruit_NeoPixel.h>

#define LED_PIN    6       // Pin connected to DIN
#define LED_COUNT  76      // Number of LEDs in your strip

const char* ssid = "HONOR";
const char* password = "12341234";
const char* hostname = "led-controller";

uint8_t prev_brightness = 0;

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

WebServer server(80);

void handleColourRequest();

void WiFiEvent(WiFiEvent_t event, arduino_event_info_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.printf("WiFi lost connection. Reason: %d\n", info.wifi_sta_disconnected.reason);
      break;
    case WIFI_EVENT_STA_CONNECTED:
      Serial.println("WiFi connected to AP");
      break;
    case WIFI_EVENT_STA_DISCONNECTED:
      Serial.println("WiFi lost connection");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.print("Got IP: ");
      Serial.println(WiFi.localIP());

      // ✅ Start mDNS and server only after IP is assigned
      if (!MDNS.begin(hostname)) {
        Serial.println("Error setting up MDNS responder!");
      } else {
        Serial.println("mDNS responder started!");
        MDNS.addService("http", "tcp", 80);
        Serial.printf("You can now ping or browse to http://%s.local\n", hostname);
      }

      server.on("/", []() { server.send(200, "text/html", "<h1>LED Controller</h1>"); });
      server.on("/set-colour", handleColourRequest);
      server.begin();
      Serial.println("HTTP server started");
      break;
    
    default:
      Serial.printf("Unhandled WiFi event: %d\n", event);
      break;
  }
}

void setup() {
  esp_bt_controller_disable();

  Serial.begin(115200);
  Serial.print("Connecting to network ");

  WiFi.onEvent(WiFiEvent);
  WiFi.mode(WIFI_STA);

  esp_wifi_set_max_tx_power(WIFI_POWER_13dBm);

  WiFi.begin(ssid, password);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);   // optional: remember credentials in flash
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.print("Connected!\n");
  
  // MDNS.begin(hostname);
  // MDNS.addService("http", "tcp", 80);
  // server.on("/", []() { server.send(200, "text/html", "<h1>LED Controller</h1>"); });
  // server.on("/set-colour", handleColourRequest);
  // server.begin();

  // Strip setup
  strip.begin();
  strip.show(); // Initialize all pixels to 'off'

  Serial.println("\nSystem Ready!");
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    server.handleClient();
  //   Serial.println("WiFi lost, reconnecting...");
  //   WiFi.disconnect();
  //   WiFi.begin(ssid, password);

  //   unsigned long startAttemptTime = millis();
  //   while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 5000) {
  //     delay(100);
  //   }

  //   if (WiFi.status() == WL_CONNECTED) {
  //     Serial.println("Reconnected!");
  //     // Re‑register mDNS service if needed
  //     MDNS.begin(hostname);
  //     MDNS.addService("http", "tcp", 80);
  } else {
    Serial.print(".");
  }
}

// Convert hex string "#RRGGBB" to RGB ints
void hexToRGB(const String& hex, uint8_t &r, uint8_t &g, uint8_t &b) {
  // Expect format "#RRGGBB"
  if (hex.length() == 7 && hex[0] == '#') {
    r = strtol(hex.substring(1, 3).c_str(), NULL, 16);
    g = strtol(hex.substring(3, 5).c_str(), NULL, 16);
    b = strtol(hex.substring(5, 7).c_str(), NULL, 16);
  } else {
    r = g = b = 0; // fallback
  }
}

void setFullColour(uint8_t r, uint8_t g, uint8_t b) {
  for(uint8_t i=0; i <strip.numPixels(); i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
}

void handleColourRequest() {
  Serial.printf("\nHandling request ...\n");

  uint8_t r = 0, g = 0, b = 0;
  if(server.hasArg("brightness")) {
    Serial.printf("Setting brightness %d", server.arg("brightness").toInt());
    strip.setBrightness(constrain(server.arg("brightness").toInt(), 0, 255));
  }

  if(server.hasArg("rgb")) {
    hexToRGB(server.arg("rgb"), r, g, b);
    Serial.printf("Setting colour %d %d %d\n", r, g, b);
    setFullColour(r, g, b);
  }
  

  strip.show();

  server.send(200, "text/plain", "OK");
}


// Rainbow cycle across all pixels
void rainbowCycle(uint8_t wait) {
  uint16_t i, j;

  for(j=0; j<256*5; j++) { // 5 cycles of all colors
    for(i=0; i<strip.numPixels(); i++) {
      strip.setPixelColor(i, Wheel(((i * 256 / strip.numPixels()) + j) & 255));
    }
    strip.show();
    delay(wait);
  }
}

// Generate rainbow colors across 0-255 positions
uint32_t Wheel(byte WheelPos) {
  WheelPos = 255 - WheelPos;
  if(WheelPos < 85) {
    return strip.Color(255 - WheelPos * 3, 0, WheelPos * 3);
  }
  if(WheelPos < 170) {
    WheelPos -= 85;
    return strip.Color(0, WheelPos * 3, 255 - WheelPos * 3);
  }
  WheelPos -= 170;
  return strip.Color(WheelPos * 3, 255 - WheelPos * 3, 0);
}
