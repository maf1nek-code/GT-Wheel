/*
  ===========================================================================
   Kierownica GT - firmware ESP32 (ESP32-WROOM-32 / ESP32 DevKit)
  ===========================================================================

   Co robi:
     - czyta 12 przyciskow kierownicy (kazdy zwiera pin do GND),
     - eliminuje drgania stykow (debounce),
     - kazda zmiane wysyla na port szeregowy (USB), np.:
           BTN 10 ON GPIO18   <- przycisk 10 wcisniety
           BTN 10 OFF GPIO18  <- przycisk 10 puszczony
     - co 1 s wysyla pelny stan wszystkich przyciskow:
           STATE 000000000100
     - odpowiada na komendy z PC (uzywa ich program w Pythonie):
           PING    -> PONG KIEROWNICA_GT <wersja> <liczba_przyciskow>
           STATE?  -> STATE ....
           INFO    -> lista przyciskow i pinow

   Arduino IDE:
     Board Manager: pakiet "esp32" by Espressif Systems
     Plytka:        "ESP32 Dev Module"
     Serial Monitor: 115200 baud
     (Windows moze potrzebowac sterownika CP210x albo CH340 - zalezy od
      ukladu USB na plytce)

   Podlaczenie przycisku:  GPIO ---[ przycisk ]--- GND
   (wewnetrzny pull-up jest wlaczony, zaden rezystor nie jest potrzebny;
    wspolny przewod GND podlacz do dowolnego pinu GND na plytce)

   Dlaczego te piny - pominiete sa piny, ktore sprawiaja problemy:
     GPIO 0, 2, 5, 12, 15  - piny "strapping" (wcisniety przycisk przy starcie
                             moze zablokowac uruchomienie / wgrywanie)
     GPIO 1, 3             - TX/RX portu szeregowego (USB)
     GPIO 6..11            - pamiec flash, nie wolno ich uzywac
     GPIO 34..39           - tylko wejscia, BEZ wewnetrznego pull-upa
   Zapasowe dobre piny: GPIO 13, 16, 17.
*/

#include <Arduino.h>

// ----------------------------- ustawienia ---------------------------------
const char*         DEVICE_ID    = "KIEROWNICA_GT";  // Python szuka tego napisu
const char*         FW_VERSION   = "1.0";
const unsigned long BAUD_RATE    = 115200;
const unsigned long DEBOUNCE_MS  = 15;    // czas stabilizacji styku
const unsigned long HEARTBEAT_MS = 1000;  // co ile wysylac pelny stan

struct Button {
  uint8_t     pin;
  const char* pinName;
};

// Kolejnosc = numer przycisku (1..12) - zgodnie z opisami na kierownicy.
// Lewa strona kierownicy -> lewa listwa plytki DevKit, prawa -> prawa.
//
//  Przycisk | stary opis (Nano) | ESP32-WROOM-32 | strona plytki
//  ---------+-------------------+----------------+--------------
//      1    |       A3          |    GPIO32      |  lewa
//      2    |       A2          |    GPIO33      |  lewa
//      3    |       D8          |    GPIO25      |  lewa
//      4    |       D10         |    GPIO26      |  lewa
//      5    |       A1          |    GPIO27      |  lewa
//      6    |      (GND)        |    GPIO23      |  prawa
//      7    |      (VIN)        |    GPIO22      |  prawa
//      8    |       A7          |    GPIO21      |  prawa
//      9    |       A6          |    GPIO19      |  prawa
//     10    |       A5          |    GPIO18      |  prawa
//     11    |       D6          |    GPIO14      |  lewa
//     12    |       D5          |    GPIO4       |  prawa
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

bool          stableState[NUM_BUTTONS];   // true = wcisniety (po debounce)
bool          lastReading[NUM_BUTTONS];   // ostatni surowy odczyt
unsigned long lastChangeMs[NUM_BUTTONS];  // kiedy surowy odczyt sie zmienil
unsigned long lastHeartbeatMs = 0;

char    cmdBuf[32];
uint8_t cmdLen = 0;

inline bool readPressed(uint8_t i) {
  // INPUT_PULLUP: puszczony = HIGH, wcisniety (zwarty do GND) = LOW
  return digitalRead(buttons[i].pin) == LOW;
}

// Na ESP32-WROOM-32 (USB przez CP210x/CH340) zawsze true. Na plytkach z
// natywnym USB (S2/S3) jest true tylko gdy PC ma otwarty port - wtedy nie
// blokujemy petli, gdy nikt nie slucha.
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
  Serial.println(NUM_BUTTONS);
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

void processCommand(char* cmd) {
  for (char* p = cmd; *p; p++) *p = toupper(*p);

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
      if (cmdLen > 0) {
        cmdBuf[cmdLen] = '\0';
        processCommand(cmdBuf);
        cmdLen = 0;
      }
    } else if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(BAUD_RATE);

  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    pinMode(buttons[i].pin, INPUT_PULLUP);
  }
  delay(5);  // chwila na ustabilizowanie pull-upow
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    stableState[i]  = readPressed(i);
    lastReading[i]  = stableState[i];
    lastChangeMs[i] = now;
  }

  // Krotko czekamy na otwarcie portu (max 1.5 s), zeby przywitanie nie zginelo.
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

  delay(1);
}
