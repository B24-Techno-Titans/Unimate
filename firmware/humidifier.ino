#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

const char* ssid = "HONOR";
const char* pass = "12341234";

WebServer server(80);

const int humidifierPin = 4;
int modeState = 0; // 0=OFF,1=CONTINUOUS,2=BLINK

// button lockout
unsigned long lastPressTime = 0;
const unsigned long LOCKOUT_MS = 1500;

void pressHumidifierButton() {
  digitalWrite(humidifierPin, LOW);
  delay(500);
  digitalWrite(humidifierPin, HIGH);
  delay(500);
}

String stateName() {
  if (modeState == 0) return "OFF";
  if (modeState == 1) return "CONTINUOUS";
  return "BLINK";
}

void handlePress() {
  unsigned long now = millis();
  if (now - lastPressTime < LOCKOUT_MS) {
    server.send(429, "application/json",
      "{\"error\":\"locked\"}");
    return;
  }

  lastPressTime = now;
  modeState = (modeState + 1) % 3;
  pressHumidifierButton();

  server.send(200, "application/json",
    String("{\"state\":") + modeState +
    ",\"name\":\"" + stateName() + "\"}");
}

void handleState() {
  server.send(200, "application/json",
    String("{\"state\":") + modeState +
    ",\"name\":\"" + stateName() + "\"}");
}

void handleRoot() {
  String page = R"rawliteral(
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Humidifier</title>
<style>
  body { font-family: system-ui; max-width:420px; margin:40px auto; text-align:center; background-color: rgb(204, 210, 234);}
  h2 { margin-bottom:10px; }
  #state { font-size:22px; margin:16px 0; }
  button {
    width:100%; padding:18px;
    font-size:22px; border:none;
    border-radius:12px;
    background:#9260c5; color:white;
  }
  button:disabled { background:#999; }
</style>
</head>
<body>
<h2>Humidifier Control</h2>
<div id="state">Loading…</div>
<button id="btn" onclick="press()">PRESS</button>
<p style="opacity:.6;margin-top:20px;">http://humidifier.local</p>

<script>
async function refresh(){
  let r = await fetch('/state');
  let j = await r.json();
  document.getElementById('state').innerText = "Mode: " + j.name;
}

async function press(){
  const b = document.getElementById('btn');
  b.disabled = true;
  b.innerText = "PRESSING";
  try {
    let r = await fetch('/press');
    let j = await r.json();
    document.getElementById('state').innerText = "Mode: " + j.name;
  } catch {}
  setTimeout(()=>{
    b.disabled = false;
    b.innerText = "PRESS";
  }, 1600);
}

refresh();
</script>
</body>
</html>
)rawliteral";

  server.send(200, "text/html", page);
}

void setup() {
  delay(2000);
  Serial.begin(115200);

  pinMode(humidifierPin, OUTPUT);
  digitalWrite(humidifierPin, HIGH);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, pass);

  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }

  Serial.println();
  Serial.println(WiFi.localIP());

  // mDNS
  if (MDNS.begin("humidifier")) {
    Serial.println("mDNS started → http://humidifier.local");
  }

  server.on("/", handleRoot);
  server.on("/press", handlePress);
  server.on("/state", handleState);
  server.begin();
}

void loop() {
  server.handleClient();
}
