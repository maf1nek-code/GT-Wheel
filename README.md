# Kierownica GT

Przyciski kierownicy do simracingu na ESP32 (Arduino Nano ESP32). ESP32 wysyła odczyty przycisków
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

## Przyciski i piny

Opisy na kierownicy to piny klasycznego **Arduino Nano**. Firmware używa ich odpowiedników GPIO
w **ESP32-S3 w formacie Nano** (Arduino Nano ESP32 i klony). Leżą one fizycznie **w tych samych
miejscach listwy**, więc płytkę ESP32 wkładasz w to samo złącze.

Każdy przycisk zwiera pin do **GND** (wspólny przewód GND na dole kierownicy).
Firmware włącza wewnętrzny pull-up, więc rezystory nie są potrzebne.

| Przycisk | Arduino Nano | ESP32 (GPIO) |
|---:|---|---|
| 1 | A3 | GPIO4 |
| 2 | A2 | GPIO3 |
| 3 | D8 | GPIO17 |
| 4 | D10 | GPIO21 |
| 5 | A1 | GPIO2 |
| 6 | ~~GND~~ → **A4** | **GPIO11** |
| 7 | ~~VIN~~ → **A0** | **GPIO1** |
| 8 | A7 | GPIO14 |
| 9 | A6 | GPIO13 |
| 10 | A5 | GPIO12 |
| 11 | D6 | GPIO9 |
| 12 | D5 | GPIO8 |

> ⚠️ **Przyciski 6 i 7:** w miejscach `GND` i `VIN` (zarówno w Nano, jak i w ESP32 Nano) są piny
> zasilania, nie wejścia. Nie da się ich odczytać, a przycisk zwierający `VIN` z `GND` robi
> zwarcie zasilania. Przepnij je na najbliższe wolne piny po tej samej stronie listwy:
> przycisk 6 → **A4 (GPIO11)**, przycisk 7 → **A0 (GPIO1)**.

## 1. Wgranie firmware (Arduino IDE)

1. *Boards Manager* → zainstaluj pakiet dla swojej płytki (patrz punkt 2).
2. *Tools → Board*:
   - oryginalne **Arduino Nano ESP32**: wybierz tę płytkę (pakiet *Arduino ESP32 Boards*);
   - klon ESP32-S3 w formacie Nano: **ESP32S3 Dev Module** (pakiet *esp32* by Espressif) i
     *Tools → USB CDC On Boot* → **Enabled**.

   Kod sam wybiera właściwą numerację pinów (nazwy Nano albo GPIO), więc nic nie trzeba przestawiać.
3. Otwórz `esp32/kierownica_gt/kierownica_gt.ino` i kliknij **Upload**.
4. Test: *Serial Monitor* na 115200 baud. Po wciśnięciu przycisku zobaczysz np. `BTN 10 ON A5`.
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
[19:26:32] Przycisk 10 (pin A5) WLACZONY
[19:26:32] Przycisk 10 (pin A5) wylaczony
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
