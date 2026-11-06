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

Każdy przycisk zwiera pin do **GND** (wspólny przewód GND na dole kierownicy).
Firmware włącza wewnętrzny pull-up, więc rezystory nie są potrzebne.

| Przycisk | Pin |
|---:|---|
| 1 | A3 |
| 2 | A2 |
| 3 | D8 |
| 4 | D10 |
| 5 | A1 |
| 6 | **D2** (na kierownicy: GND – przepiąć!) |
| 7 | **D3** (na kierownicy: VIN – przepiąć!) |
| 8 | A7 |
| 9 | A6 |
| 10 | A5 |
| 11 | D6 |
| 12 | D5 |

> ⚠️ **Przyciski 6 i 7:** `GND` i `VIN` to piny zasilania, nie wejścia, więc ESP32 nie może ich
> odczytać. Do tego przycisk, który zwiera `VIN` ze wspólnym `GND`, robi zwarcie zasilania.
> Przepnij przewody tych przycisków z `GND`/`VIN` na **D2** i **D3**. Możesz też użyć innych wolnych
> pinów (D4, D7, D9, D11, D12, A0, A4) i poprawić tabelę `buttons[]` w pliku `.ino`.

## 1. Wgranie firmware (Arduino IDE)

1. *Boards Manager* → zainstaluj **Arduino ESP32 Boards**.
2. *Tools → Board* → **Arduino Nano ESP32**, *Tools → Pin Numbering* → **By Arduino pin (default)**.
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
