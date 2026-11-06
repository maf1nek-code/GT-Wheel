/*
  ===========================================================================
   Kierownica GT - firmware ESP32 (ESP32-S3 w formacie Nano)
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

   Piny:
     Opisy na kierownicy (A3, D8, ...) to piny klasycznego Arduino Nano.
     Ponizej uzyte sa ich odpowiedniki GPIO w ESP32-S3 w formacie Nano
     (Arduino Nano ESP32 i klony) - fizycznie te SAME miejsca na listwie,
     wiec plytke wkladasz w to samo gniazdo/zlacze.

   Arduino IDE:
     Plytka: "Arduino Nano ESP32" (pakiet "Arduino ESP32 Boards")
             albo dla klona: "ESP32S3 Dev Module" (pakiet "esp32" by Espressif,
             wtedy Tools -> USB CDC On Boot: "Enabled").
     Kod sam wybiera wlasciwa numeracje pinow - nic nie trzeba przestawiac.
     Serial Monitor: 115200 baud

   Podlaczenie przycisku:  PIN ---[ przycisk ]--- GND
   (wewnetrzny pull-up jest wlaczony, zaden rezystor nie jest potrzebny)

   !!! UWAGA - przyciski 6 i 7 !!!
     Na kierownicy byly podpiete do "GND" i "VIN". W tych miejscach listwy
     (zarowno w Nano, jak i w ESP32 Nano) sa piny ZASILANIA, nie wejscia -
     nie da sie ich odczytac, a przycisk zwierajacy VIN z GND = zwarcie!
     Przepnij je na najblizsze wolne piny po tej samej stronie listwy:
        przycisk 6: z "GND" -> A4 (GPIO11)
        przycisk 7: z "VIN" -> A0 (GPIO1)
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

// PIN(nazwa_Nano, GPIO_ESP32):
//  - plytka "Arduino Nano ESP32" -> uzywa nazwy z Nano (core sam przelicza),
//  - kazda inna plytka ESP32-S3  -> uzywa bezposrednio numeru GPIO.
#if defined(ARDUINO_NANO_ESP32)
  #define PIN(nanoName, gpio) (nanoName)
#else
  #define PIN(nanoName, gpio) (gpio)
#endif

// Kolejnosc = numer przycisku (1..12) - zgodnie z opisami na kierownicy.
//
//  Przycisk | Arduino Nano | ESP32 (GPIO)
//  ---------+--------------+-------------
//      1    |     A3       |   GPIO4
//      2    |     A2       |   GPIO3
//      3    |     D8       |   GPIO17
//      4    |     D10      |   GPIO21
//      5    |     A1       |   GPIO2
//      6    |  (GND) A4    |   GPIO11   <- przepnij z GND na A4
//      7    |  (VIN) A0    |   GPIO1    <- przepnij z VIN na A0
//      8    |     A7       |   GPIO14
//      9    |     A6       |   GPIO13
//     10    |     A5       |   GPIO12
//     11    |     D6       |   GPIO9
//     12    |     D5       |   GPIO8
Button buttons[] = {
  { PIN(A3,  4),  "A3/GPIO4"   },  //  1
  { PIN(A2,  3),  "A2/GPIO3"   },  //  2
  { PIN(D8,  17), "D8/GPIO17"  },  //  3
  { PIN(D10, 21), "D10/GPIO21" },  //  4
  { PIN(A1,  2),  "A1/GPIO2"   },  //  5
  { PIN(A4,  11), "A4/GPIO11"  },  //  6  (na kierownicy bylo GND)
  { PIN(A0,  1),  "A0/GPIO1"   },  //  7  (na kierownicy bylo VIN)
  { PIN(A7,  14), "A7/GPIO14"  },  //  8
  { PIN(A6,  13), "A6/GPIO13"  },  //  9
  { PIN(A5,  12), "A5/GPIO12"  },  // 10
  { PIN(D6,  9),  "D6/GPIO9"   },  // 11
  { PIN(D5,  8),  "D5/GPIO8"   },  // 12
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
