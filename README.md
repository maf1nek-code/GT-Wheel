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
| `pc/konfigurator.py` | konfigurator: obsługa kierownicy i efektów LED w tle, otwiera okno z `pc/ui` |
| `pc/ui/` | wygląd konfiguratora (HTML/CSS/JS) |
| `pc/led_efekty.py` | liczenie efektów LED (obroty, zmiana biegu, pit limiter, flagi) |
| `pc/telemetria.py` | odczyt telemetrii z AC, ACC i Le Mans Ultimate (z spotterem) |
| `pc/firmware.py` | aktualizacja firmware: wydania z GitHuba + esptool |
| `.github/workflows/firmware.yml` | budowanie firmware i publikowanie wydań |
| `pc/requirements.txt` | biblioteki Pythona |
| `Kierownica_GT.bat` | uruchamianie dwuklikiem (sam instaluje biblioteki za 1. razem) |
| `Konfigurator_GT.bat` | uruchamianie konfiguratora dwuklikiem |

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

Zapasowe dobre piny: GPIO 16 i 17 (GPIO 13 jest zajęty przez pasek LED).

## Pasek LED (opcjonalny)

Pasek WS2812B (np. 8–24 diody) pokazuje obroty silnika i stany specjalne. Kolory liczy program
na PC, a ESP32 tylko je wyświetla, więc zmiana kolorów nie wymaga ponownego wgrywania firmware.

| Pasek | ESP32 |
|---|---|
| DIN | **GPIO13** przez rezystor ok. 330 Ω |
| 5V | pin **VIN/5V** płytki |
| GND | **GND** |

- Przy zasilaniu z USB trzymaj jasność ≤ 40%. Każda dioda świecąca na biało na 100% pobiera
  ok. 60 mA. Przy dłuższym pasku użyj osobnego zasilacza 5 V (GND wspólne z ESP32).
- Firmware obsługuje do 60 diod. Bez danych z PC przez 3 s pasek gaśnie.
- Bez paska możesz zostawić firmware bez zmian albo ustawić `LED_ENABLED` na `0`.

## 1. Wgranie firmware (Arduino IDE)

1. *Boards Manager* → zainstaluj pakiet **esp32** by Espressif Systems.
   *Tools → Manage Libraries* → zainstaluj **Adafruit NeoPixel** (do paska LED).
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
| `PONG KIEROWNICA_GT 1.1 12 LED 60` | odpowiedź na `PING` (po niej PC rozpoznaje kierownicę; `LED 60` = obsługa paska do 60 diod) |

| Od PC | Znaczenie |
|---|---|
| `PING` / `STATE?` / `INFO` | powitanie / pełny stan przycisków / lista pinów |
| `LEDS RRGGBBRRGGBB…` | kolory paska (6 znaków hex na diodę, jasność już uwzględniona) |
| `LEDS` | zgaś pasek |

## 2. Sterownik wirtualnego kontrolera (Windows)

Wybierz jeden:

- **vJoy (zalecany do simracingu)**: zwykły joystick z przyciskami 1–12, które w grze widać jako
  „Przycisk 10” itd. Pobierz z <https://github.com/BrunnerInnovation/vJoy/releases>, potem w
  *Configure vJoy* włącz urządzenie 1 z co najmniej **12 przyciskami**.
- **Pad Xbox 360 (ViGEmBus)**: instaluje się razem z biblioteką `vgamepad`. Jeśli instalator się
  nie pojawi, pobierz go z <https://github.com/nefarius/ViGEmBus/releases>.
  Przypisania są w `XBOX_MAPPING` w `kierownica.py`.

Domyślny tryb `auto` używa vJoy, a gdy go nie ma, pada Xbox.

## 3. Konfigurator (test przycisków i diody LED)

Kliknij dwukrotnie **`Konfigurator_GT.bat`**. Otworzy się okno konfiguratora (Microsoft Edge
w trybie aplikacji, bez pasków przeglądarki – Edge jest w każdym Windows 10/11), a przy zegarze
pojawi się **ikona Kierownica GT**.

**Program działa w tle.** Po zamknięciu okna zostaje przy zegarze: trzyma połączenie z kierownicą,
przekazuje przyciski do gier (vJoy / pad Xbox) i steruje diodami z telemetrii. Okno otwierasz
z powrotem dwuklikiem ikony (albo jeszcze raz `Konfigurator_GT.bat`), a program kończysz z menu ikony
(prawy przycisk → **Zakończ**). Kropka na ikonie: zielona – kierownica połączona, pomarańczowa –
szukanie, czerwona – port zajęty. Dzięki temu `Kierownica_GT.bat` nie jest już potrzebny.

**Ustawienia** (zakładka w oknie):

- **Uruchamiaj z systemem Windows** – po włączeniu komputera program startuje w tle, bez okna,
  tylko z ikoną przy zegarze. Wpis trafia do autostartu bieżącego użytkownika (bez uprawnień
  administratora); wyłączenie przełącznika go usuwa.
- **Otwieraj okno przy autostarcie**, **Po zamknięciu okna**: działaj w tle albo zakończ program.
- **Kontroler w grach**: automatycznie / vJoy (z numerem urządzenia) / pad Xbox 360 / wyłączony.
- **Steruj diodami w czasie gry**, **Powiadomienia przy zegarze** (podłączenie kierownicy, nowy firmware).
- O programie: wersja, folder, aktualizacja firmware, zakończenie programu.

Komunikaty programu działającego w tle zapisują się w `pc/kierownica_gt.log`.

**Test przycisków**: rysunek tej kierownicy (karbonowa płyta, pasek 16 diod, ekran, 10 kolorowych
przycisków i 3 pokrętła). Wciśnięty przycisk świeci, sprawdzony dostaje ✓, a ekran na rysunku pokazuje
ostatnio wciśnięty przycisk, jego pin, czas trzymania i postęp testu. Pasek diod na rysunku świeci tak
samo jak prawdziwy. Przycisk wciśnięty już w chwili połączenia pulsuje na pomarańczowo – może to
oznaczać zwarcie pinu do GND. Obok jest lista pinów i dziennik.

**Przypisz przyciski**: ustala, który numer przycisku z firmware jest w którym miejscu rysunku.
Klikasz miejsce na rysunku i wciskasz ten przycisk na kierownicy (program sam przechodzi do następnego
miejsca). Układ zapisuje się w `pc/uklad_kierownicy.json`. Domyślny układ jest zgadnięty z tabeli pinów:
lewa strona 1–5 i lewe pokrętło 11, prawa strona 6–10 i prawe pokrętło 12.

**Diody LED**:

- podgląd na żywo i symulacja: jazda (obroty ręcznie albo automatycznie), pit limiter, flagi,
  gra wyłączona; przełącznik **Na kierownicy** pokazuje to samo na prawdziwym pasku,
- liczba diod, jasność (z wyliczeniem poboru prądu), kierunek zapalania,
- kolory: zaznaczasz diody myszką (przeciągnięcie, Shift = zakres, Ctrl = pojedyncze) i wybierasz
  kolor; są gotowe zestawy, własny gradient i odbicie lustrzane,
- progi obrotów na jednym suwaku z trzema znacznikami (pierwsza dioda, wszystkie, zmiana biegu),
- stany specjalne z podglądem każdego z nich: zmiana biegu, pit limiter (3 wzory), flaga żółta
  i niebieska (na skrajnych diodach albo całym pasku), gra wyłączona (zgaszone, stały, oddech, skaner),
- **Zapisz** (Ctrl+S) zapisuje do `pc/leds.json` – z tego pliku będzie korzystał program w czasie gry,
- **Profile**: osobne zestawy ustawień, np. dla każdej gry (`pc/profile_led/`), plus eksport
  i import do pliku.

`pc/leds.json` i profile nie są w gicie, więc aktualizacje ich nie nadpiszą.

W podglądzie jest też tryb **Gra na żywo**: gdy gra działa, panel pod paskiem pokazuje, co program
z niej odczytuje (obroty, bieg, pit limiter, flaga), a pasek świeci jak w czasie jazdy. Tak najłatwiej
ustawić progi pod konkretne auto.

## 4. Diody w czasie gry (telemetria)

Obsługiwane gry: **Assetto Corsa**, **Assetto Corsa Competizione** i **Le Mans Ultimate**.
Uruchom grę i **`Kierownica_GT.bat`** (jak zawsze). Program sam wykryje grę i będzie sterował paskiem
według ustawień z konfiguratora (`pc/leds.json`):

- obroty → kolejne diody, od progu „zmiana biegu” cały pasek miga,
- pit limiter, flaga żółta i niebieska → efekty ze „Stanów specjalnych”,
- **spotter** (ACC i Le Mans Ultimate): auto obok ciebie zapala skrajne diody po jego stronie.
  Assetto Corsa nie podaje pozycji innych aut, więc tam spotter nie działa. Jeśli w którejś grze
  strony wyjdą odwrotnie, w karcie „Spotter” włącz „Zamień lewą i prawą stronę”,
- menu, pauza, powtórka albo brak gry → efekt „Gra wyłączona”.

Wystarczy, że program działa przy zegarze (np. z autostartem) – w czasie gry okno może być zamknięte.
Gdy okno jest otwarte, pasek pokazuje podgląd z konfiguratora (tryb **Gra na żywo** pokazuje grę).

Stary sposób też działa: `Kierownica_GT.bat` (okno konsoli, opcja `--bez-diod`), ale **nie uruchamiaj
go razem z konfiguratorem** – oba używają tego samego portu COM.

| Gra | Skąd dane | Co trzeba zrobić |
|---|---|---|
| Assetto Corsa | wbudowana pamięć współdzielona | nic |
| Assetto Corsa Competizione | wbudowana pamięć współdzielona | nic |
| Le Mans Ultimate | wtyczka rF2SharedMemoryMapPlugin | włączyć wtyczkę (poniżej) |

**Le Mans Ultimate – włączenie wtyczki** (tylko jeśli konfigurator pisze, że gra „nie udostępnia
danych”; jeśli używasz SimHub albo CrewChief, zwykle jest już włączona):

1. Pobierz `rFactor2SharedMemoryMapPlugin64.dll` (projekt *rF2SharedMemoryMapPlugin* autora
   TheIronWolfModding na GitHubie) i skopiuj go do folderu gry `Le Mans Ultimate\Plugins\`.
2. Uruchom grę raz i zamknij. W pliku `Le Mans Ultimate\UserData\player\CustomPluginVariables.JSON`
   przy `rFactor2SharedMemoryMapPlugin64.dll` ustaw `" Enabled": 1`.
3. Uruchom grę ponownie.

Sprawdzenie bez kierownicy (w folderze projektu, po pierwszym uruchomieniu `.bat`):
`pc\.venv\Scripts\python.exe pc\telemetria.py` wypisuje na żywo odczyty z gry.

## 5. Aktualizacja firmware z konfiguratora

Po pierwszym wgraniu przez Arduino IDE kolejne wersje wgrywa konfigurator: kliknij status połączenia
(prawy górny róg) → **Aktualizacja firmware**. Gdy jest nowsza wersja, na stronie głównej pojawia się
też pasek „Dostępna nowa wersja firmware”. Aktualizacja trwa ok. 30 s, idzie tym samym kablem USB,
a ustawienia diod i układ przycisków zostają na komputerze.

- Pliki firmware buduje **GitHub Actions** (`.github/workflows/firmware.yml`) przy każdej zmianie
  w `esp32/`. Na gałęzi głównej powstaje wydanie `fw-<wersja>`, które konfigurator pobiera.
  Żeby wydać nową wersję, podnieś `FW_VERSION` w `kierownica_gt.ino`.
- **Wgraj z pliku .bin…** – plik z Arduino IDE (*Szkic → Eksportuj skompilowany plik binarny*,
  najlepiej `kierownica_gt.ino.merged.bin`) albo pobrany z zakładki Releases na GitHubie.
- Wgrywa narzędzie **esptool** (to samo co w Arduino IDE), instalowane automatycznie przez `.bat`.
- Gdy wgrywanie nie może się połączyć: przytrzymaj **BOOT** na płytce, kliknij „Aktualizuj” i puść
  BOOT, gdy pojawi się „Łączenie”.

## 6. Uruchomienie

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
