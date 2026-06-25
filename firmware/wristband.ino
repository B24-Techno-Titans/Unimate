#include <WiFi.h>
#include "esp_wifi.h"
#include "esp_bt.h"
#include <WebServer.h>
#include <ESPmDNS.h>

#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "spo2_algorithm.h"

#define ROLLING_AVG_SIZE 5
#define BUFFER_SIZE 50

// --- LM35 analog temperature sensor ---
#define LM35_PIN 1          // ESP32-C3 SuperMini silkscreen pin "1" = GPIO1 (ADC1_CH1)
#define LM35_SAMPLES 8      // oversampling to smooth analog noise

const char* ssid = "HONOR"; // Wi-Fi name
const char* password = "12341234"; // Wi-Fi Password

const char* mdns_hostname = "unimate-esp";

MAX30105 particleSensor;
WebServer server(80);

unsigned long previousMillis = 0; // For async functionality

uint32_t irBuffer[BUFFER_SIZE];
uint32_t redBuffer[BUFFER_SIZE];

int32_t spo2, heartRate;
int8_t validSPO2 = 0, validHeartRate = 0;
bool hrOK = false, wifiOK = false;
float latestTemp = 0.0;

float prevBPM[ROLLING_AVG_SIZE];
uint8_t beatUpdateIndex = 0; // next index to be updated

bool initHRsensor() {
  if (particleSensor.begin(Wire, I2C_SPEED_STANDARD) == false) {
    Serial.println("MAX30102 was not found. Please check wiring/power.");
    return false;
    // while (1)
    //   ;
  }

  particleSensor.setup();  //Configure sensor. Use 6.4mA for LED drive
  particleSensor.setPulseAmplitudeIR(0x1F);  // ~7.6 mA
  particleSensor.setPulseAmplitudeRed(0x1F);
  particleSensor.setPulseAmplitudeGreen(0);

  // for(int i = 0; i<ROLLING_AVG_SIZE; i++) {
  //   prevBPM[i] = 0.0;
  // }

  return true;
}

void initTempSensor() {
  pinMode(LM35_PIN, INPUT);
  // ESP32 ADC defaults to 12-bit / 11dB attenuation, which covers the
  // 0-500mV range an LM35 outputs over a 0-50°C span with plenty of margin.
}

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
      if (!MDNS.begin(mdns_hostname)) {
        Serial.println("Error setting up MDNS responder!");
      } else {
        Serial.println("mDNS responder started!");
        MDNS.addService("http", "tcp", 80);
        Serial.printf("You can now ping or browse to http://%s.local\n", mdns_hostname);
      }

      server.on("/data", HTTP_GET, sendJSON);
      server.begin();
      Serial.println("HTTP server started");
      break;
    
    default:
      Serial.printf("Unhandled WiFi event: %d\n", event);
      break;
  }
}

bool initWifiConnection() {
  // connect to Wi-Fi
  WiFi.onEvent(WiFiEvent);
  WiFi.mode(WIFI_STA);

  esp_wifi_set_max_tx_power(WIFI_POWER_13dBm);

  // WiFi.disconnect(true);
  WiFi.begin(ssid, password);

  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("");
  Serial.println("WiFi connected.");
  Serial.print("ESP32 IP Address: ");
  Serial.println(WiFi.localIP());
  
  // if (!MDNS.begin(mdns_hostname)) { 
  //   Serial.println("Error setting up MDNS responder!");
  //   return false;
  // } else {
  //   Serial.println("mDNS responder started!");
  //   Serial.print("You can now ping or browse to 'http://");
  //   Serial.print(mdns_hostname);
  //   Serial.println(".local'");
  // }

  // MDNS.addService("http", "tcp", 80);

  // server.on("/data", HTTP_GET, sendJSON);
  // server.begin();
  // Serial.println("HTTP server started");

  return true;
}

float getRollingBPM() {
  float beatsPerMinute = 0.0;
  uint8_t count = 0;

  for(; count<ROLLING_AVG_SIZE; count++) {
    if(prevBPM[count] < 20.0) break;
    beatsPerMinute += prevBPM[count];
  }

  beatsPerMinute /= count;
  return beatsPerMinute;
}

void updateBPM() {
  // Gather samples for SPO2/HR
  for (int i = 0; i < BUFFER_SIZE; i++) {
    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    delay(10);
  }

  maxim_heart_rate_and_oxygen_saturation(
    irBuffer, BUFFER_SIZE, redBuffer,
    &spo2, &validSPO2, &heartRate, &validHeartRate
  );
}

float readLM35Temperature() {
  uint32_t mvSum = 0;
  for (int i = 0; i < LM35_SAMPLES; i++) {
    mvSum += analogReadMilliVolts(LM35_PIN); // calibrated mV reading using eFuse ADC calibration
    delay(2);
  }
  float avgMilliVolts = mvSum / (float)LM35_SAMPLES;

  // LM35: 10mV per °C, 0V = 0°C
  return avgMilliVolts / 10.0;
}

void sendJSON() {
  String jsonResponse = "{";
  jsonResponse += "\"heartRate\":" + String(validHeartRate ? heartRate : 0) + ",";
  jsonResponse += "\"spO2\":" + String(validSPO2 ? spo2 : 0) + ",";
  jsonResponse += "\"temperature\":" + String(latestTemp, 1);
  jsonResponse += "}";

  server.send(200, "application/text", jsonResponse);
}

void setup() {
  esp_bt_controller_disable();

  #if defined(ESP32)
    Serial.begin(115200);
    Wire.begin(6, 5);
  #else
    Serial.begin(9600);
    Wire.begin();
  #endif

  // Initialize sensors
  hrOK = initHRsensor();
  initTempSensor();

  wifiOK = initWifiConnection();

  if(hrOK && wifiOK)
    Serial.println("Setup Completed Successfully\n");

}

void loop() {
  if(WiFi.status() == WL_CONNECTED) {
    server.handleClient();

    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis >= 5000) {
      previousMillis = currentMillis;

      updateBPM();
      latestTemp = readLM35Temperature();

      Serial.print("\nHeart Rate:");
      Serial.println(heartRate);

      Serial.print("SpO2: ");
      Serial.println(spo2);
      
      Serial.print("Temp: ");
      Serial.print(latestTemp, 1);
      Serial.println(" C");
    }
  } else {
    Serial.print(".");
  }

  if(!hrOK) {
    hrOK = initHRsensor();
  }
}
