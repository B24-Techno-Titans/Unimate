#include <WiFi.h>
#include "esp_wifi.h"
#include "esp_bt.h"
#include <WebServer.h>
#include <ESPmDNS.h>
#include <HardwareSerial.h>
#include <ESP32Servo.h>
#include <math.h>

/* ===================== CONFIGURATION ===================== */
const char* ssid = "HONOR";
const char* password = "12341234";
const char* hostname = "smart-fan";

#define FAN_BTN_PIN 4
#define RADAR_RX 0
#define RADAR_TX 1
#define SERVO_PIN 2

/* ===================== STATE & OBJECTS ===================== */
WebServer server(80);
Servo trackingServo;
HardwareSerial radar(1);

enum class FanState : uint8_t { FAN_OFF, FAN_SPEED_1, FAN_SPEED_2 };
FanState currentState = FanState::FAN_OFF;

/* ===================== FAN CONTROL ===================== */
void pressFanButton() {
  digitalWrite(FAN_BTN_PIN, HIGH);
  delay(150); // Short pulse is okay
  digitalWrite(FAN_BTN_PIN, LOW);
  delay(150);
}

void handleSpeedRequest() {
  if(server.hasArg("speed")) {
    int newState = server.arg("speed").toInt();
    if(newState > 2) newState = 2;
    if(newState < 0) newState = 0;
    String msg = "Current State: " + String(static_cast<uint8_t>(currentState)) + "\tNew State: " + newState + "\n";
    
    uint8_t stateDiff = (newState+ 3) - static_cast<uint8_t>(currentState);
    stateDiff %= 3;
    msg += "StateDiff = " + String(stateDiff);
    Serial.println(msg);

    for(int i=0; i<stateDiff; i++) {
      pressFanButton();
    }
    currentState = static_cast<FanState>(newState);
  } else {
    pressFanButton();
  }

  server.send(200);
}

/* ===================== SETUP ===================== */

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

      server.on("/", []() { server.send(200, "text/html", "<h1>Smart Fan Radar Controller</h1>"); });
      server.on("/set-speed", handleSpeedRequest);
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
  pinMode(FAN_BTN_PIN, OUTPUT);
  digitalWrite(FAN_BTN_PIN, LOW);

  // WiFi Setup
  Serial.print("Connecting to network ");
  WiFi.onEvent(WiFiEvent);
  WiFi.mode(WIFI_STA);

  esp_wifi_set_max_tx_power(WIFI_POWER_13dBm);

  WiFi.begin(ssid, password);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.print("Connected!\n");
  
  // MDNS.begin(hostname);
  // server.on("/", []() { server.send(200, "text/html", "<h1>Smart Fan Radar Controller</h1>"); });
  // server.on("/set-speed", handleSpeedRequest);
  // server.begin();

  Serial.println("\nSystem Ready!");
}

/* ===================== LOOP ===================== */
void loop() {
  server.handleClient(); // Handle Web Requests
}