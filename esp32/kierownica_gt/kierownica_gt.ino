/*
  ===========================================================================
   Kierownica GT - firmware ESP32 (Arduino Nano ESP32 / klon Nano ESP32-S3)
  ===========================================================================

   Co robi:
     - czyta 12 przyciskow kierownicy (kazdy zwiera pin do GND),
     - eliminuje drgania stykow (debounce),
     - kazda zmiane wysyla na port szeregowy (USB), np.:
           BTN 10 ON A5      <- przycisk 10 wcisniety (pin A5)
           BTN 10 OFF A5     <- przycisk 10 puszczony
     - co 1 s wysyla pelny stan wszystkich przyciskow:
           STATE 000000000100
     - odpowiada na komendy z PC (uzywa ich program w Pythonie):
           PING    -> PONG KIEROWNICA_GT <wersja> <liczba_przyciskow>
           STATE?  -> STATE ....
           INFO    -> lista przyciskow i pinow

   Arduino IDE:
     Plytka:  "Arduino Nano ESP32"  (pakiet "Arduino ESP32 Boards" w Board Managerze)
     Tools -> Pin Numbering: "By Arduino pin (default)"
     Serial Monitor: 115200 baud

   Podlaczenie przycisku:  PIN ---[ przycisk ]--- GND
   (wewnetrzny pull-up jest wlaczony, zaden rezystor nie jest potrzebny)

   !!! UWAGA - przyciski 6 i 7 !!!
     Na kierownicy przycisk 6 jest podpiety do "GND", a przycisk 7 do "VIN".
     To NIE sa piny wejsciowe - ESP32 nie jest w stanie ich odczytac,
     a przycisk zwierajacy VIN z GND robi zwarcie zasilania!
     Przepnij przewody tych dwoch przyciskow na wolne piny D2 i D3
     (albo inne wolne: D4, D7, D9, D11, D12, A0, A4) i ewentualnie popraw
     tabele ponizej.
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
// GPIO w nawiasach dotyczy Arduino Nano ESP32 (gdyby trzeba bylo przejsc
// na numeracje "By GPIO number").
Button buttons[] = {
  { A3,  "A3"  },  //  1  (GPIO4)
  { A2,  "A2"  },  //  2  (GPIO3)
  { D8,  "D8"  },  //  3  (GPIO17)
  { D10, "D10" },  //  4  (GPIO21)
  { A1,  "A1"  },  //  5  (GPIO2)
  { D2,  "D2"  },  //  6  (GPIO5)  <- na kierownicy byl GND, PRZEPNIJ na D2
  { D3,  "D3"  },  //  7  (GPIO6)  <- na kierownicy byl VIN, PRZEPNIJ na D3
  { A7,  "A7"  },  //  8  (GPIO14)
  { A6,  "A6"  },  //  9  (GPIO13)
  { A5,  "A5"  },  // 10  (GPIO12)
  { D6,  "D6"  },  // 11  (GPIO9)
  { D5,  "D5"  },  // 12  (GPIO8)
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

// Na natywnym USB (Nano ESP32) "Serial" jest prawdziwe tylko gdy PC ma
// otwarty port - dzieki temu nie blokujemy petli, gdy nikt nie slucha.
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
