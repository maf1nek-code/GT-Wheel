# GT Wheel

Sim-racing wheel buttons on an ESP32 (ESP32-WROOM-32 / ESP32 DevKit). The ESP32 sends button readings
over USB (serial port), and a Python program turns them into a virtual game controller on Windows.

```
[buttons] -> ESP32 --USB/COM--> kierownica.py -> vJoy / Xbox 360 pad -> game
```

The configurator's interface and the program messages are in Polish. Where this README names a button
or a tab, the Polish label is given in quotes with an English translation.

## Structure

| File | Description |
|---|---|
| `esp32/gt_wheel/gt_wheel.ino` | firmware, uploaded from the Arduino IDE |
| `pc/kierownica.py` | PC program: port auto-detection + controller emulation |
| `pc/konfigurator.py` | configurator: runs the wheel and the LED effects in the background, opens the window from `pc/ui` |
| `pc/ui/` | the configurator's interface (HTML/CSS/JS) |
| `pc/led_efekty.py` | LED effects (revs, shift light, pit limiter, flags) |
| `pc/telemetria.py` | telemetry from AC, ACC and Le Mans Ultimate (with spotter) |
| `pc/firmware.py` | firmware updates: GitHub releases + esptool |
| `.github/workflows/firmware.yml` | builds the firmware and publishes releases |
| `pc/requirements.txt` | Python libraries |
| `led-strip-mount/` | 3D-printable case and holder for the LED strip (STEP + STL) |
| `GT_Wheel.bat` | double-click to run (installs the libraries on first run) |
| `GT_Wheel_Configurator.bat` | double-click to run the configurator |

The Python file names stay in Polish on purpose: Windows autostart points to `pc/konfigurator.py`,
so renaming it would break autostart for existing installs.

## Buttons and pins (ESP32-WROOM-32 / ESP32 DevKit)

Each button shorts a pin to **GND**. Connect the common GND wire to any GND pin on the board.
The firmware enables the internal pull-ups, so no resistors are needed.
Buttons on the left side of the wheel go to the left header of the board, buttons on the right side to the right one.

| Button | old label (Nano) | ESP32-WROOM-32 | board side |
|---:|---|---|---|
| 1 | A3 | **GPIO32** (D32) | left |
| 2 | A2 | **GPIO33** (D33) | left |
| 3 | D8 | **GPIO25** (D25) | left |
| 4 | D10 | **GPIO26** (D26) | left |
| 5 | A1 | **GPIO27** (D27) | left |
| 6 | GND | **GPIO23** (D23) | right |
| 7 | VIN | **GPIO22** (D22) | right |
| 8 | A7 | **GPIO21** (D21) | right |
| 9 | A6 | **GPIO19** (D19) | right |
| 10 | A5 | **GPIO18** (D18) | right |
| 11 | D6 | **GPIO14** (D14) | left |
| 12 | D5 | **GPIO4** (D4) | right |

On DevKit boards the pins are usually labelled `D32`, `D33` and so on, or just with numbers.

Pins that cause trouble are skipped:

- GPIO 0, 2, 5, 12, 15: strapping pins. A button held down at power-up can block booting or uploading.
- GPIO 1 and 3: TX/RX of the USB port.
- GPIO 6–11: flash memory.
- GPIO 34–39: input only, no pull-up.

Spare good pins: GPIO 16 and 17 (GPIO 13 is used by the LED strip).

## LED strip (optional)

A WS2812B strip (e.g. 8–24 LEDs) shows engine revs and special states. The colours are computed by the
PC program and the ESP32 only displays them, so changing colours never requires re-uploading the firmware.

| Strip | ESP32 |
|---|---|
| DIN | **GPIO13** through a resistor of about 330 Ω |
| 5V | the board's **VIN/5V** pin |
| GND | **GND** |

- On USB power keep the brightness at 40% or less. Each LED lit full white at 100% draws about 60 mA.
  For a longer strip use a separate 5 V supply (GND shared with the ESP32).
- The firmware supports up to 60 LEDs. The strip turns off after 3 s without data from the PC.
- Without a strip you can leave the firmware as it is, or set `LED_ENABLED` to `0`.

The `led-strip-mount/` folder has a 3D-printable case for a 70 mm strip and a two-part holder
(body + lid), with print-ready parts in `led-strip-mount/print/`.

## 1. Uploading the firmware (Arduino IDE)

1. *Boards Manager* → install the **esp32** package by Espressif Systems.
   *Tools → Manage Libraries* → install **Adafruit NeoPixel** (for the LED strip).
2. *Tools → Board* → **ESP32 Dev Module**. On Windows you may need the **CP210x** or **CH340**
   driver, depending on the USB chip on your board.
3. Open `esp32/gt_wheel/gt_wheel.ino` and click **Upload**. If the upload hangs on
   `Connecting...`, hold the **BOOT** button on the board.
4. Test: *Serial Monitor* at 115200 baud. Pressing a button prints e.g. `BTN 10 ON GPIO18`.
   The `INFO` command lists the pins.
   **Close the Serial Monitor before starting the Python program**, because it holds the port.

Protocol (text, 115200 baud):

| From the ESP32 | Meaning |
|---|---|
| `BTN <nr> ON <pin>` / `BTN <nr> OFF <pin>` | a button changed state |
| `STATE 000000000100` | full state, sent every 1 s (1 = pressed) |
| `PONG KIEROWNICA_GT 1.1 12 LED 60` | reply to `PING` (the PC recognises the wheel by it; `LED 60` = supports a strip of up to 60 LEDs) |

| From the PC | Meaning |
|---|---|
| `PING` / `STATE?` / `INFO` | hello / full button state / pin list |
| `LEDS RRGGBBRRGGBB…` | strip colours (6 hex characters per LED, brightness already applied) |
| `LEDS` | turn the strip off |

The `KIEROWNICA_GT` identifier in `PONG` is part of the protocol and stays as it is, so older firmware and the PC program keep recognising each other.

## 2. Virtual controller driver (Windows)

Pick one:

- **vJoy (recommended for sim racing)**: a regular joystick with buttons 1–12, shown in games as
  "Button 10" and so on. Download it from <https://github.com/BrunnerInnovation/vJoy/releases>, then in
  *Configure vJoy* enable device 1 with at least **12 buttons**.
- **Xbox 360 pad (ViGEmBus)**: installed together with the `vgamepad` library. If the installer
  doesn't appear, download it from <https://github.com/nefarius/ViGEmBus/releases>.
  The button mapping is in `XBOX_MAPPING` in `kierownica.py`.

The default `auto` mode uses vJoy, and the Xbox pad when vJoy isn't installed.

## 3. Configurator (button test and LEDs)

Double-click **`GT_Wheel_Configurator.bat`**. The configurator window opens (Microsoft Edge in app
mode, without browser bars – Edge comes with every Windows 10/11), and a **GT Wheel icon** appears
next to the clock.

**The program runs in the background.** After you close the window it stays next to the clock: it keeps
the connection to the wheel, passes the buttons to games (vJoy / Xbox pad) and drives the LEDs from
telemetry. Open the window again by double-clicking the icon (or running `GT_Wheel_Configurator.bat`
again), and quit from the icon menu (right-click → "Zakończ", Quit). The dot on the icon: green – wheel
connected, orange – searching, red – port busy. Thanks to this, `GT_Wheel.bat` is no longer needed.

**Settings** ("Ustawienia" tab):

- **Start with Windows** – after the computer starts, the program runs in the background without a
  window, only with the icon next to the clock. The entry goes to the current user's autostart (no
  administrator rights needed); turning the switch off removes it.
- **Open the window on autostart**, **When the window is closed**: keep running in the background or quit.
- **Controller in games**: automatic / vJoy (with device number) / Xbox 360 pad / off.
- **Drive the LEDs while playing**, **Notifications next to the clock** (wheel connected, new firmware).
- About: version, folder, firmware update, quit.

Messages from the background program are written to `pc/kierownica_gt.log`.

**Button test** ("Test przycisków"): a drawing of this wheel (carbon plate, 16-LED strip, screen, 10
coloured buttons and 3 rotary knobs). A pressed button lights up, a checked one gets a ✓, and the screen
on the drawing shows the last pressed button, its pin, how long it was held and the test progress. The
LED strip on the drawing lights up exactly like the real one. A button that is already pressed when the
wheel connects pulses orange – it may mean the pin is shorted to GND. Next to it there is a pin list and a log.

**Assign buttons** ("Przypisz przyciski"): sets which firmware button number sits where on the drawing.
Click a spot on the drawing and press that button on the wheel (the program moves on to the next spot by
itself). The layout is saved in `pc/uklad_kierownicy.json`. The default layout is guessed from the pin
table: left side 1–5 and left knob 11, right side 6–10 and right knob 12.

**LEDs** ("Diody LED"):

- live preview and simulation: driving (revs by hand or automatic), pit limiter, flags, game off; the
  "Na kierownicy" (on the wheel) switch shows the same on the real strip,
- number of LEDs, brightness (with a current draw estimate), lighting direction,
- colours: select LEDs with the mouse (drag, Shift = range, Ctrl = single) and pick a colour; there
  are presets, a custom gradient and mirroring,
- rev thresholds on one slider with three markers (first LED, all LEDs, shift point),
- start-up animation (white wave or rainbow), played once when the wheel connects,
- special states, each with a preview: shift point, pit limiter (3 patterns), yellow and blue flag
  (on the outer LEDs or the whole strip), game off (waiting – centre LEDs dimmed, off, steady,
  breathing, scanner),
- **Save** ("Zapisz", Ctrl+S) writes to `pc/leds.json` – the program uses this file while you play,
- **Profiles**: separate sets of settings, e.g. one per game (`pc/profile_led/`), plus export
  and import to a file.

`pc/leds.json` and the profiles are not in git, so updates never overwrite them.

The preview also has a **live game** mode ("Gra na żywo"): while a game is running, the panel under the
strip shows what the program reads from it (revs, gear, pit limiter, flag), and the strip lights up as
it would while driving. This is the easiest way to set thresholds for a specific car.

## 4. LEDs while playing (telemetry)

Supported games: **Assetto Corsa**, **Assetto Corsa Competizione** and **Le Mans Ultimate**.
Start the game and **`GT_Wheel.bat`** (as usual). The program detects the game by itself and drives the
strip according to the configurator settings (`pc/leds.json`):

- revs → LEDs light up one after another, from the shift threshold the whole strip blinks,
- pit limiter, yellow and blue flag → the effects from the special states,
- **spotter** (ACC and Le Mans Ultimate): a car next to you lights the outer LEDs on its side.
  Assetto Corsa doesn't provide other cars' positions, so the spotter doesn't work there. If the sides
  come out reversed in a game, turn on "Zamień lewą i prawą stronę" (swap left and right) in the
  "Spotter" card,
- menu, pause, replay or no game → the "game off" effect.

It's enough that the program runs next to the clock (e.g. with autostart) – the window can be closed
while you play. When the window is open, the strip shows the configurator preview (the live game mode
shows the game).

The old way still works: `GT_Wheel.bat` (console window, `--bez-diod` option to disable the LEDs), but
**don't run it together with the configurator** – both use the same COM port.

| Game | Data source | What to do |
|---|---|---|
| Assetto Corsa | built-in shared memory | nothing |
| Assetto Corsa Competizione | built-in shared memory | nothing |
| Le Mans Ultimate | rF2SharedMemoryMapPlugin plugin | enable the plugin (below) |

**Le Mans Ultimate – enabling the plugin** (only if the configurator says the game "doesn't share
data"; if you use SimHub or CrewChief, it's usually enabled already):

1. Download `rFactor2SharedMemoryMapPlugin64.dll` (the *rF2SharedMemoryMapPlugin* project by
   TheIronWolfModding on GitHub) and copy it to the game folder `Le Mans Ultimate\Plugins\`.
2. Start the game once and quit. In `Le Mans Ultimate\UserData\player\CustomPluginVariables.JSON`,
   set `" Enabled": 1` for `rFactor2SharedMemoryMapPlugin64.dll`.
3. Start the game again.

Checking without the wheel (in the project folder, after the first run of the `.bat`):
`pc\.venv\Scripts\python.exe pc\telemetria.py` prints live readings from the game.

## 5. Firmware updates from the configurator

After the first upload from the Arduino IDE, the configurator installs new versions: click the
connection status (top right) → "Aktualizacja firmware" (firmware update). When a newer version is
available, the home page also shows a "new firmware available" bar. The update takes about 30 s, uses
the same USB cable, and the LED settings and button layout stay on the computer.

- The firmware files are built by **GitHub Actions** (`.github/workflows/firmware.yml`) on every change
  in `esp32/`. On the main branch it creates an `fw-<version>` release, which the configurator downloads.
  To release a new version, bump `FW_VERSION` in `gt_wheel.ino`.
- **Upload from a .bin file…** – a file from the Arduino IDE (*Sketch → Export Compiled Binary*,
  preferably `gt_wheel.ino.merged.bin`) or one downloaded from the Releases tab on GitHub.
- The upload uses **esptool** (the same tool the Arduino IDE uses), installed automatically by the `.bat`.
- If the upload can't connect: hold **BOOT** on the board, click "Aktualizuj" (update) and release
  BOOT when "Łączenie" (connecting) appears.

## 6. Running

Double-click **`GT_Wheel.bat`**. Python 3 from <https://python.org> is required, installed with
*Add python.exe to PATH* ticked.
On the first run the script creates `pc\.venv` and installs the libraries.

The program finds the COM port with the wheel by itself (it sends `PING` to every port and waits for a
reply), and then prints the readings (in Polish):

```
[19:26:31] Polaczono z kierownica na porcie COM5 (12 przyciskow). Gotowe!
[19:26:32] Przycisk 10 (pin GPIO18) WLACZONY
[19:26:32] Przycisk 10 (pin GPIO18) wylaczony
```

("Connected to the wheel on COM5 (12 buttons). Ready!", then button 10 pressed and released.)

When the cable is unplugged, all virtual buttons are released and the program searches for the wheel again.

Options (add them to the `.bat` or pass them on the command line):

```
GT_Wheel.bat --backend xbox     # force the Xbox 360 pad
GT_Wheel.bat --backend vjoy     # force vJoy
GT_Wheel.bat --backend konsola  # console preview only, no emulation
GT_Wheel.bat --port COM5        # skip auto-detection
GT_Wheel.bat --list             # list COM ports
```
