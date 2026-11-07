# Kierownica GT

Przyciski kierownicy do simracingu na ESP32 (ESP32-WROOM-32 / ESP32 DevKit). ESP32 wysyła odczyty przycisków
przez USB (port szeregowy), a program w Pythonie zamienia je na wirtualny kontroler do gier w Windows.

```
[przyciski] -> ESP32 --USB/COM--> kierownica.py -> vJoy / pad Xbox 360 -> gra
```

## Struktura

| Plik | Opis |
|---|---|
| `esp32/kierownica_gt/kierownica_gt.ino` | firmware do wgrania z Arduino IDE |
| `pc/kierownica.py` | program na PC: autowykrywanie portu + emulacja kontrolera |
| `pc/requirements.txt` | biblioteki Pythona |
| `Kierownica_GT.bat` | uruchamianie dwuklikiem (sam instaluje biblioteki za 1. razem) |

## Przyciski i piny (ESP32-WROOM-32 / ESP32 DevKit)

Każdy przycisk zwiera pin do **GND**. Wspólny przewód GND podłącz do dowolnego pinu GND na płytce.
Firmware włącza wewnętrzny pull-up, więc rezystory nie są potrzebne.
Przyciski z lewej strony kierownicy idą na lewą listwę płytki, a z prawej strony na prawą.

| Przycisk | stary opis (Nano) | ESP32-WROOM-32 | strona płytki |
|---:|---|---|---|
| 1 | A3 | **GPIO32** (D32) | lewa |
| 2 | A2 | **GPIO33** (D33) | lewa |
| 3 | D8 | **GPIO25** (D25) | lewa |
| 4 | D10 | **GPIO26** (D26) | lewa |
| 5 | A1 | **GPIO27** (D27) | lewa |
| 6 | GND | **GPIO23** (D23) | prawa |
| 7 | VIN | **GPIO22** (D22) | prawa |
| 8 | A7 | **GPIO21** (D21) | prawa |
| 9 | A6 | **GPIO19** (D19) | prawa |
| 10 | A5 | **GPIO18** (D18) | prawa |
| 11 | D6 | **GPIO14** (D14) | lewa |
| 12 | D5 | **GPIO4** (D4) | prawa |

Na płytkach DevKit piny są zwykle opisane jako `D32`, `D33` itd. albo samymi numerami.

Pominięte są piny, które sprawiają problemy:

- GPIO 0, 2, 5, 12, 15: piny „strapping”. Przycisk wciśnięty przy starcie może zablokować uruchomienie albo wgrywanie.
- GPIO 1 i 3: TX/RX portu USB.
- GPIO 6–11: pamięć flash.
- GPIO 34–39: tylko wejścia, bez pull-upa.

Zapasowe dobre piny: GPIO 13, 16 i 17.

## 1. Wgranie firmware (Arduino IDE)

1. *Boards Manager* → zainstaluj pakiet **esp32** by Espressif Systems.
2. *Tools → Board* → **ESP32 Dev Module**. W Windows może być potrzebny sterownik **CP210x**
   albo **CH340**, zależnie od układu USB na płytce.
3. Otwórz `esp32/kierownica_gt/kierownica_gt.ino` i kliknij **Upload**. Jeśli wgrywanie stoi na
   `Connecting...`, przytrzymaj przycisk **BOOT** na płytce.
4. Test: *Serial Monitor* na 115200 baud. Po wciśnięciu przycisku zobaczysz np. `BTN 10 ON GPIO18`.
   Komenda `INFO` wypisuje listę pinów.
   **Przed uruchomieniem programu w Pythonie zamknij Serial Monitor**, bo zajmuje port.

Protokół (tekst, 115200 baud):

| Od ESP32 | Znaczenie |
|---|---|
| `BTN <nr> ON <pin>` / `BTN <nr> OFF <pin>` | zmiana stanu przycisku |
| `STATE 000000000100` | pełny stan, wysyłany co 1 s (1 = wciśnięty) |
| `PONG KIEROWNICA_GT 1.0 12` | odpowiedź na `PING` (po niej PC rozpoznaje kierownicę) |

## 2. Sterownik wirtualnego kontrolera (Windows)

Wybierz jeden:

- **vJoy (zalecany do simracingu)**: zwykły joystick z przyciskami 1–12, które w grze widać jako
  „Przycisk 10” itd. Pobierz z <https://github.com/BrunnerInnovation/vJoy/releases>, potem w
  *Configure vJoy* włącz urządzenie 1 z co najmniej **12 przyciskami**.
- **Pad Xbox 360 (ViGEmBus)**: instaluje się razem z biblioteką `vgamepad`. Jeśli instalator się
  nie pojawi, pobierz go z <https://github.com/nefarius/ViGEmBus/releases>.
  Przypisania są w `XBOX_MAPPING` w `kierownica.py`.

Domyślny tryb `auto` używa vJoy, a gdy go nie ma, pada Xbox.

## 3. Uruchomienie

Kliknij dwukrotnie **`Kierownica_GT.bat`**. Wymagany jest Python 3 z <https://python.org>, z
zaznaczoną opcją *Add python.exe to PATH*.
Przy pierwszym uruchomieniu skrypt utworzy `pc\.venv` i zainstaluje biblioteki.

Program sam znajdzie port COM z kierownicą (wysyła `PING` na każdy port i czeka na odpowiedź),
a potem wypisuje odczyty:

```
[19:26:31] Polaczono z kierownica na porcie COM5 (12 przyciskow). Gotowe!
[19:26:32] Przycisk 10 (pin GPIO18) WLACZONY
[19:26:32] Przycisk 10 (pin GPIO18) wylaczony
```

Po odłączeniu kabla wszystkie wirtualne przyciski zostają puszczone, a program szuka kierownicy od nowa.

Opcje (można je dopisać do `.bat` albo podać w wierszu poleceń):

```
Kierownica_GT.bat --backend xbox     # wymuś pad Xbox 360
Kierownica_GT.bat --backend vjoy     # wymuś vJoy
Kierownica_GT.bat --backend konsola  # tylko podgląd, bez emulacji
Kierownica_GT.bat --port COM5        # pomiń autowykrywanie
Kierownica_GT.bat --list             # lista portów COM
```
