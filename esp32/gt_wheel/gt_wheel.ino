/*
  ===========================================================================
   GT Wheel - ESP32 firmware (ESP32-WROOM-32 / ESP32 DevKit)
  ===========================================================================

   What it does:
     - reads the 12 wheel buttons (each one shorts a pin to GND),
     - debounces the contacts,
     - sends every change to the serial port (USB), e.g.:
           BTN 10 ON GPIO18   <- button 10 pressed
           BTN 10 OFF GPIO18  <- button 10 released
     - sends the full state of all buttons every 1 s:
           STATE 000000000100
     - answers commands from the PC (used by the Python program):
           PING    -> PONG KIEROWNICA_GT <version> <button_count> [LED <max_leds>]
           STATE?  -> STATE ....
           INFO    -> list of buttons and pins
           LEDS RRGGBBRRGGBB...  -> LED strip colours (6 hex characters per LED)
           LEDS               -> turn the strip off
     - drives a WS2812B LED strip (revs, effects) - the colours are computed
       by the PC program, the ESP32 only displays them. The strip turns off
       after 3 s without data.

   Arduino IDE:
     Board Manager: "esp32" package by Espressif Systems
     Board:         "ESP32 Dev Module"
     Serial Monitor: 115200 baud
     (Windows may need the CP210x or CH340 driver, depending on the USB
      chip on the board)

   Button wiring:  GPIO ---[ button ]--- GND
   (the internal pull-up is enabled, no resistor is needed;
    connect the common GND wire to any GND pin on the board)

   Why these pins - pins that cause trouble are skipped:
     GPIO 0, 2, 5, 12, 15  - strapping pins (a button held down at power-up
                             can block booting / uploading)
     GPIO 1, 3             - TX/RX of the serial port (USB)
     GPIO 6..11            - flash memory, must not be used
     GPIO 34..39           - input only, NO internal pull-up
   Spare good pins: GPIO 16, 17 (GPIO 13 is used by the LED strip).

   WS2812B LED strip (optional):
     DIN  <- GPIO13 through a resistor of about 330 ohm
     5V   <- the board's VIN/5V pin (keep the brightness low on USB power)
     GND  <- board GND
   Requires the "Adafruit NeoPixel" library (Arduino IDE: Tools -> Manage
   Libraries -> type "Adafruit NeoPixel" -> Install).
   Without a strip / the library: set LED_ENABLED to 0.
*/

#define LED_ENABLED 1   // 1 = LED strip support, 0 = off (no library needed)

#include <Arduino.h>
#if LED_ENABLED
#include <Adafruit_NeoPixel.h>
#endif

// ------------------------------ settings ----------------------------------
const char*         DEVICE_ID    = "KIEROWNICA_GT";  // the Python program looks for this string
const char*         FW_VERSION   = "1.1";
const unsigned long BAUD_RATE    = 115200;
const unsigned long DEBOUNCE_MS  = 15;    // contact settling time
const unsigned long HEARTBEAT_MS = 1000;  // how often to send the full state

const uint8_t       LED_PIN        = 13;    // WS2812B strip DIN
const uint16_t      LED_MAX        = 60;    // maximum number of LEDs
const unsigned long LED_TIMEOUT_MS = 3000;  // no data from the PC -> the strip turns off

struct Button {
  uint8_t     pin;
  const char* pinName;
};

// Order = button number (1..12) - matches the labels on the wheel.
// Left side of the wheel -> left header of the DevKit board, right -> right.
//
//   Button  | old label (Nano)  | ESP32-WROOM-32 | board side
//  ---------+-------------------+----------------+--------------
//      1    |       A3          |    GPIO32      |  left
//      2    |       A2          |    GPIO33      |  left
//      3    |       D8          |    GPIO25      |  left
//      4    |       D10         |    GPIO26      |  left
//      5    |       A1          |    GPIO27      |  left
//      6    |      (GND)        |    GPIO23      |  right
//      7    |      (VIN)        |    GPIO22      |  right
//      8    |       A7          |    GPIO21      |  right
//      9    |       A6          |    GPIO19      |  right
//     10    |       A5          |    GPIO18      |  right
//     11    |       D6          |    GPIO14      |  left
//     12    |       D5          |    GPIO4       |  right
Button buttons[] = {
  { 32, "GPIO32" },  //  1
  { 33, "GPIO33" },  //  2
  { 25, "GPIO25" },  //  3
  { 26, "GPIO26" },  //  4
  { 27, "GPIO27" },  //  5
  { 23, "GPIO23" },  //  6
  { 22, "GPIO22" },  //  7
  { 21, "GPIO21" },  //  8
  { 19, "GPIO19" },  //  9
  { 18, "GPIO18" },  // 10
  { 14, "GPIO14" },  // 11
  {  4, "GPIO4"  },  // 12
};

const uint8_t NUM_BUTTONS = sizeof(buttons) / sizeof(buttons[0]);
// --------------------------------------------------------------------------

bool          stableState[NUM_BUTTONS];   // true = pressed (after debounce)
bool          lastReading[NUM_BUTTONS];   // last raw reading
unsigned long lastChangeMs[NUM_BUTTONS];  // when the raw reading changed
unsigned long lastHeartbeatMs = 0;

// Fits "LEDS " + 60 LEDs * 6 hex characters.
char     cmdBuf[16 + LED_MAX * 6];
uint16_t cmdLen = 0;
bool     cmdOverflow = false;

#if LED_ENABLED
Adafruit_NeoPixel strip(LED_MAX, LED_PIN, NEO_GRB + NEO_KHZ800);
unsigned long lastLedFrameMs = 0;
bool          ledsLit        = false;
#endif

inline bool readPressed(uint8_t i) {
  // INPUT_PULLUP: released = HIGH, pressed (shorted to GND) = LOW
  return digitalRead(buttons[i].pin) == LOW;
}

// Always true on the ESP32-WROOM-32 (USB through CP210x/CH340). On boards with
// native USB (S2/S3) it is true only while the PC has the port open - so the
// loop doesn't block when nobody is listening.
inline bool hostConnected() {
  return (bool)Serial;
}

void sendHello(const char* prefix) {
  Serial.print(prefix);
  Serial.print(' ');
  Serial.print(DEVICE_ID);
  Serial.print(' ');
  Serial.print(FW_VERSION);
  Serial.print(' ');
  Serial.print(NUM_BUTTONS);
#if LED_ENABLED
  Serial.print(" LED ");
  Serial.print(LED_MAX);
#endif
  Serial.println();
}

void sendState() {
  if (!hostConnected()) return;
  char bits[NUM_BUTTONS + 1];
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    bits[i] = stableState[i] ? '1' : '0';
  }
  bits[NUM_BUTTONS] = '\0';
  Serial.print("STATE ");
  Serial.println(bits);
}

void sendButton(uint8_t i) {
  if (!hostConnected()) return;
  Serial.print("BTN ");
  Serial.print(i + 1);
  Serial.print(stableState[i] ? " ON " : " OFF ");
  Serial.println(buttons[i].pinName);
}

void sendInfo() {
  sendHello("INFO");
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    Serial.print("INFO BTN ");
    Serial.print(i + 1);
    Serial.print(" PIN ");
    Serial.print(buttons[i].pinName);
    Serial.println(stableState[i] ? " ON" : " OFF");
  }
}

#if LED_ENABLED
int8_t hexValue(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

void ledsOff() {
  strip.clear();
  strip.show();
  ledsLit = false;
}

// hex = "RRGGBBRRGGBB..." (upper case); LEDs without data turn off.
void setLeds(const char* hex) {
  uint16_t len = strlen(hex);
  uint16_t count = len / 6;
  if (count > LED_MAX) count = LED_MAX;

  for (uint16_t i = 0; i < count * 6; i++) {
    if (hexValue(hex[i]) < 0) return;  // broken frame - keep the previous one
  }

  strip.clear();
  for (uint16_t i = 0; i < count; i++) {
    const char* p = hex + i * 6;
    strip.setPixelColor(i,
                        (hexValue(p[0]) << 4) | hexValue(p[1]),
                        (hexValue(p[2]) << 4) | hexValue(p[3]),
                        (hexValue(p[4]) << 4) | hexValue(p[5]));
  }
  strip.show();
  ledsLit        = count > 0;
  lastLedFrameMs = millis();
}
#endif

void processCommand(char* cmd) {
  for (char* p = cmd; *p; p++) *p = toupper(*p);

#if LED_ENABLED
  if (strncmp(cmd, "LEDS", 4) == 0 && (cmd[4] == '\0' || cmd[4] == ' ')) {
    const char* hex = cmd + 4;
    while (*hex == ' ') hex++;
    if (*hex == '\0') {
      ledsOff();
    } else {
      setLeds(hex);
    }
    return;
  }
#endif

  if (strcmp(cmd, "PING") == 0) {
    sendHello("PONG");
  } else if (strcmp(cmd, "STATE?") == 0) {
    sendState();
  } else if (strcmp(cmd, "INFO") == 0) {
    sendInfo();
  }
}

void handleSerialInput() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0 && !cmdOverflow) {
        cmdBuf[cmdLen] = '\0';
        processCommand(cmdBuf);
      }
      cmdLen      = 0;
      cmdOverflow = false;  // a line that is too long is dropped as a whole
    } else if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    } else {
      cmdOverflow = true;
    }
  }
}

void setup() {
  Serial.setRxBufferSize(1024);  // an LED frame for 60 LEDs is ~370 characters
  Serial.begin(BAUD_RATE);

  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    pinMode(buttons[i].pin, INPUT_PULLUP);
  }
  delay(5);  // give the pull-ups a moment to settle

#if LED_ENABLED
  strip.begin();
  strip.clear();
  strip.show();
#endif
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    stableState[i]  = readPressed(i);
    lastReading[i]  = stableState[i];
    lastChangeMs[i] = now;
  }

  // Wait briefly for the port to open (max 1.5 s) so the greeting isn't lost.
  unsigned long start = millis();
  while (!Serial && millis() - start < 1500) {
    delay(10);
  }
  if (hostConnected()) {
    sendHello("HELLO");
    sendState();
  }
}

void loop() {
  unsigned long now = millis();

  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    bool reading = readPressed(i);

    if (reading != lastReading[i]) {
      lastReading[i]  = reading;
      lastChangeMs[i] = now;
    }

    if (reading != stableState[i] && (now - lastChangeMs[i]) >= DEBOUNCE_MS) {
      stableState[i] = reading;
      sendButton(i);
    }
  }

  handleSerialInput();

  if (now - lastHeartbeatMs >= HEARTBEAT_MS) {
    lastHeartbeatMs = now;
    sendState();
  }

#if LED_ENABLED
  // The PC stopped sending (program closed, cable) - turn the strip off.
  if (ledsLit && millis() - lastLedFrameMs >= LED_TIMEOUT_MS) {
    ledsOff();
  }
#endif

  delay(1);
}
