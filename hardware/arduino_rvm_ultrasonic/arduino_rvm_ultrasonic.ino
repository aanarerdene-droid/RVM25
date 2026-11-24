// HC-SR04 across the chute: TRIG -> D9, ECHO -> D10, VCC -> 5V, GND -> GND.
// For non-5V boards, level-shift the 5V ECHO signal appropriately.
const byte TRIG_PIN = 9;
const byte ECHO_PIN = 10;
const float DETECT_THRESHOLD_CM = 14.0f;
const unsigned long CLEAR_COOLDOWN_MS = 800;
const unsigned long PING_INTERVAL_MS = 5000;
const unsigned long SAMPLE_INTERVAL_MS = 60;

bool bottleInChute = false;
bool clearTiming = false;
unsigned long clearStarted = 0, lastSample = 0, lastPing = 0;

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.begin(9600);
  Serial.println("READY:XOT17_RVM");
}

void loop() {
  unsigned long now = millis();
  if (now - lastPing >= PING_INTERVAL_MS) {
    lastPing = now;
    Serial.println("PING");
  }
  if (now - lastSample < SAMPLE_INTERVAL_MS) return;
  lastSample = now;
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 25000UL);
  float distanceCm = (duration * 0.0343f) / 2.0f;
  // A timeout is not a clear chute: wait for a valid observation.
  if (distanceCm <= 1.0f) { clearTiming = false; return; }
  if (distanceCm < DETECT_THRESHOLD_CM) {
    if (!bottleInChute) digitalWrite(LED_BUILTIN, HIGH);
    bottleInChute = true;
    clearTiming = false;
  } else if (bottleInChute) {
    if (!clearTiming) { clearTiming = true; clearStarted = now; }
    else if (now - clearStarted >= CLEAR_COOLDOWN_MS) {
      bottleInChute = false;
      clearTiming = false;
      digitalWrite(LED_BUILTIN, LOW);
      Serial.println("BOTTLE:1");
    }
  }
}
