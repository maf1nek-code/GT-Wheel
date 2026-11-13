#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kierownica GT - most: ESP32 (port szeregowy) -> wirtualny kontroler do gier,
a telemetria z gry -> pasek LED w kierownicy.

1. Sam znajduje port COM, do ktorego podlaczone jest ESP32 z firmware
   "kierownica_gt" (wysyla PING i czeka na "PONG KIEROWNICA_GT").
2. Nasluchuje ten port: "BTN 10 ON" -> wirtualny przycisk 10 wcisniety.
3. Po odlaczeniu kabla puszcza wszystkie przyciski i szuka kierownicy ponownie.
4. Czyta telemetrie z gry (Assetto Corsa, ACC, Le Mans Ultimate) i steruje
   paskiem LED wg ustawien z konfiguratora (plik leds.json).

Emulacja kontrolera (Windows):
  * vJoy     - "zwykly" joystick DirectInput z przyciskami 1..12.
               Najlepszy do simracingu (w grze widzisz "Przycisk 10").
               Wymaga sterownika vJoy: https://github.com/BrunnerInnovation/vJoy/releases
  * xbox     - wirtualny pad Xbox 360 (biblioteka vgamepad + sterownik ViGEmBus).
  * konsola  - bez emulacji, tylko wypisuje odczyty (test).
  * auto     - (domyslnie) vJoy jesli jest zainstalowany, w przeciwnym razie Xbox.

Uzycie:
  python kierownica.py                 # wszystko automatycznie
  python kierownica.py --backend xbox  # wymus pad Xbox 360
  python kierownica.py --port COM5     # pomin autowykrywanie
  python kierownica.py --list          # pokaz porty COM
  python kierownica.py --bez-diod      # nie steruj paskiem LED
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Brak biblioteki pyserial. Zainstaluj ja poleceniem:  pip install pyserial")
    sys.exit(1)

import led_efekty as fx
import telemetria

# ------------------------------- ustawienia -------------------------------
DEVICE_ID = "KIEROWNICA_GT"   # musi zgadzac sie z firmware ESP32
BAUD_RATE = 115200
PROBE_TIMEOUT_S = 3.0          # ile czekac na odpowiedz z jednego portu
SILENCE_TIMEOUT_S = 5.0        # ESP wysyla STATE co 1 s - cisza = rozlaczenie
RESCAN_DELAY_S = 2.0           # przerwa miedzy kolejnymi skanami portow

# Producenci ukladow USB, ktore zwykle siedza na plytkach ESP32 - sprawdzane najpierw.
KNOWN_VIDS = {
    0x303A,  # Espressif (natywne USB ESP32-S2/S3/C3)
    0x2341,  # Arduino (Arduino Nano ESP32)
    0x1A86,  # WCH CH340/CH9102
    0x10C4,  # Silicon Labs CP210x
    0x0403,  # FTDI
}

# Mapowanie przycisk kierownicy -> przycisk pada Xbox 360 (tylko backend "xbox").
# Przycisk "Guide" pominiety celowo - otwiera Xbox Game Bar w Windows.
XBOX_MAPPING = {
    1: "XUSB_GAMEPAD_A",
    2: "XUSB_GAMEPAD_B",
    3: "XUSB_GAMEPAD_X",
    4: "XUSB_GAMEPAD_Y",
    5: "XUSB_GAMEPAD_LEFT_SHOULDER",
    6: "XUSB_GAMEPAD_RIGHT_SHOULDER",
    7: "XUSB_GAMEPAD_BACK",
    8: "XUSB_GAMEPAD_START",
    9: "XUSB_GAMEPAD_LEFT_THUMB",
    10: "XUSB_GAMEPAD_RIGHT_THUMB",
    11: "XUSB_GAMEPAD_DPAD_UP",
    12: "XUSB_GAMEPAD_DPAD_DOWN",
}
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


class ConnectionLost(Exception):
    pass


# =============================== emulacja ==================================

class Backend:
    """Bazowa klasa wirtualnego kontrolera."""

    name = "tylko konsola (bez emulacji)"

    def __init__(self) -> None:
        self._pressed: set[int] = set()

    def set_button(self, number: int, pressed: bool) -> None:
        if pressed:
            self._pressed.add(number)
        else:
            self._pressed.discard(number)
        self._apply(number, pressed)

    def release_all(self) -> None:
        for number in sorted(self._pressed):
            self._apply(number, False)
        self._pressed.clear()

    def close(self) -> None:
        self.release_all()

    def _apply(self, number: int, pressed: bool) -> None:
        pass


class VJoyBackend(Backend):
    def __init__(self, device_id: int = 1) -> None:
        super().__init__()
        import pyvjoy  # noqa: WPS433 - import opcjonalny

        self._dev = pyvjoy.VJoyDevice(device_id)
        self.name = f"vJoy (urzadzenie {device_id})"
        for n in range(1, 13):
            self._dev.set_button(n, 0)

    def _apply(self, number: int, pressed: bool) -> None:
        self._dev.set_button(number, 1 if pressed else 0)


class XboxBackend(Backend):
    name = "wirtualny pad Xbox 360 (ViGEm)"

    def __init__(self) -> None:
        super().__init__()
        import vgamepad as vg  # noqa: WPS433 - import opcjonalny

        self._pad = vg.VX360Gamepad()
        self._map = {n: getattr(vg.XUSB_BUTTON, btn) for n, btn in XBOX_MAPPING.items()}
        self._warned: set[int] = set()
        self._pad.reset()
        self._pad.update()

    def _apply(self, number: int, pressed: bool) -> None:
        button = self._map.get(number)
        if button is None:
            if number not in self._warned:
                self._warned.add(number)
                log(f"Przycisk {number} nie ma przypisania w XBOX_MAPPING - pomijam.")
            return
        if pressed:
            self._pad.press_button(button=button)
        else:
            self._pad.release_button(button=button)
        self._pad.update()


def create_backend(choice: str, vjoy_id: int) -> Backend:
    errors = []

    if choice in ("auto", "vjoy"):
        try:
            return VJoyBackend(vjoy_id)
        except Exception as exc:  # brak pyvjoy, sterownika lub urzadzenie zajete
            errors.append(f"vJoy: {exc}")
            if choice == "auto" and not isinstance(exc, ImportError):
                log(f"vJoy niedostepny ({exc}) - probuje pada Xbox.")
            if choice == "vjoy":
                log("Nie udalo sie uruchomic vJoy: " + str(exc))
                log("Zainstaluj sterownik vJoy i wlacz urzadzenie nr "
                    f"{vjoy_id} w 'Configure vJoy' (min. 12 przyciskow).")
                sys.exit(1)

    if choice in ("auto", "xbox"):
        try:
            return XboxBackend()
        except Exception as exc:  # brak vgamepad albo sterownika ViGEmBus
            errors.append(f"Xbox/ViGEm: {exc}")
            if choice == "xbox":
                log("Nie udalo sie uruchomic pada Xbox: " + str(exc))
                log("Zainstaluj: pip install vgamepad  oraz sterownik ViGEmBus.")
                sys.exit(1)

    if choice == "auto":
        log("UWAGA: nie znaleziono vJoy ani ViGEmBus - dzialam tylko w trybie konsoli.")
        for err in errors:
            log("   " + err)
    return Backend()


# ============================ wykrywanie portu =============================

def list_candidate_ports() -> list:
    ports = []
    for p in list_ports.comports():
        if "BTHENUM" in (p.hwid or "").upper():
            continue  # porty Bluetooth - wolno sie otwieraja i to na pewno nie ESP
        ports.append(p)
    ports.sort(key=lambda p: (0 if p.vid in KNOWN_VIDS else 1, p.device))
    return ports


@dataclass
class DeviceInfo:
    n_buttons: int = 12
    version: str = "?"
    max_leds: int = 0      # 0 = firmware bez obslugi paska LED


def parse_hello(line: str) -> DeviceInfo | None:
    """'PONG KIEROWNICA_GT 1.1 12 LED 60' -> DeviceInfo(12, '1.1', 60), inaczej None."""
    parts = line.split()
    if len(parts) >= 2 and parts[0] in ("PONG", "HELLO") and parts[1] == DEVICE_ID:
        info = DeviceInfo()
        if len(parts) >= 3:
            info.version = parts[2]
        if len(parts) >= 4 and parts[3].isdigit():
            info.n_buttons = int(parts[3])
        if len(parts) >= 6 and parts[4] == "LED" and parts[5].isdigit():
            info.max_leds = int(parts[5])
        return info
    return None


def probe(port: str, busy: list[str]):
    """Sprawdza, czy na porcie jest kierownica. Zwraca (serial, DeviceInfo) albo None."""
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=0.1, write_timeout=0.5)
    except serial.SerialException as exc:
        text = str(exc).lower()
        if "denied" in text or "odmowa" in text or "busy" in text or "permission" in text:
            busy.append(port)
        return None
    except (OSError, ValueError):
        return None

    try:
        deadline = time.monotonic() + PROBE_TIMEOUT_S
        last_ping = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_ping >= 0.5:
                last_ping = now
                try:
                    ser.write(b"PING\n")
                except serial.SerialTimeoutException:
                    pass
            line = ser.readline().decode("ascii", errors="ignore").strip()
            info = parse_hello(line)
            if info is not None:
                ser.timeout = 0.2
                return ser, info
    except (serial.SerialException, OSError):
        pass

    try:
        ser.close()
    except Exception:
        pass
    return None


def wait_for_device(port_arg: str | None):
    """Skanuje porty do skutku. Zwraca (nazwa_portu, serial, DeviceInfo)."""
    announced = False
    while True:
        names = [port_arg] if port_arg else [p.device for p in list_candidate_ports()]
        if not announced:
            log("Szukam kierownicy na portach: " + (", ".join(names) if names else "(brak portow COM)"))

        busy: list[str] = []
        for name in names:
            result = probe(name, busy)
            if result:
                ser, info = result
                return name, ser, info

        if not announced:
            log("Nie znaleziono kierownicy. Podlacz ESP32 przez USB - szukam dalej... (Ctrl+C konczy)")
            if busy:
                log("Porty zajete przez inny program: " + ", ".join(busy)
                    + " (zamknij np. Serial Monitor w Arduino IDE).")
            announced = True
        time.sleep(RESCAN_DELAY_S)


# ============================== diody LED ==================================

class DiodyZGry(threading.Thread):
    """Telemetria z gry -> efekty z leds.json -> komendy LEDS do kierownicy."""

    FPS = 60

    def __init__(self, ser, max_leds: int, czytnik, zapis_lock: threading.Lock) -> None:
        super().__init__(daemon=True)
        self.ser = ser
        self.max_leds = max_leds
        self.czytnik = czytnik
        self.zapis_lock = zapis_lock
        self.stop = threading.Event()
        self._u = None
        self._mtime = None

    def _ustawienia(self) -> dict:
        try:
            mtime = fx.PLIK_USTAWIEN.stat().st_mtime
        except OSError:
            mtime = None
        if self._u is None or mtime != self._mtime:
            try:
                self._u = fx.wczytaj()
                if self._mtime is not None or mtime is not None:
                    log("Wczytano ustawienia diod (leds.json)." if mtime else
                        "Brak pliku leds.json - diody z ustawieniami domyslnymi.")
            except ValueError as exc:
                log(f"{exc} - diody z ustawieniami domyslnymi.")
                self._u = fx.domyslne_ustawienia()
            self._mtime = mtime
        return self._u

    def _wyslij(self, linia: str) -> bool:
        try:
            with self.zapis_lock:
                self.ser.write((linia + "\n").encode("ascii"))
            return True
        except (serial.SerialException, OSError):
            return False

    def run(self) -> None:
        t0 = time.monotonic()
        ostatnia, wyslano, sprawdzono = "", 0.0, -9.0
        opis = None
        u = self._ustawienia()
        while not self.stop.is_set():
            teraz = time.monotonic()
            if teraz - sprawdzono > 1.0:
                sprawdzono = teraz
                u = self._ustawienia()
            stan = self.czytnik.odczyt()
            komunikat = stan.opis if stan.gra or not opis else opis
            if komunikat != opis:
                opis = komunikat
                log(f"Diody: {opis}")
            powitanie = fx.animacja_startu(u, teraz - t0)   # raz, zaraz po podlaczeniu
            kolory = (powitanie or fx.klatka(u, stan.telemetria(), teraz - t0))[:self.max_leds]
            linia = fx.komenda_leds(fx.z_jasnoscia(kolory, u["jasnosc"]))
            # ~70% przepustowosci 115200 bodow; to samo co poprzednio - tylko raz na sekunde
            if teraz - wyslano >= max(1.0 / self.FPS, len(linia) / 8000.0) and \
                    (linia != ostatnia or teraz - wyslano >= 1.0):
                if not self._wyslij(linia):
                    return
                ostatnia, wyslano = linia, teraz
            self.stop.wait(1.0 / self.FPS)
        self._wyslij("LEDS")

    def zatrzymaj(self) -> None:
        self.stop.set()
        self.join(timeout=1.0)


# =============================== nasluch ===================================

def listen(ser, backend: Backend, n_buttons: int, zapis_lock: threading.Lock | None = None) -> None:
    state: dict[int, bool] = {}

    def apply(number: int, pressed: bool, pin: str = "", sync: bool = False) -> None:
        if not 1 <= number <= max(n_buttons, 32):
            return
        if state.get(number, False) == pressed:
            return
        state[number] = pressed
        backend.set_button(number, pressed)
        info = f" (pin {pin})" if pin else ""
        note = " [synchronizacja]" if sync else ""
        log(f"Przycisk {number:>2}{info} {'WLACZONY' if pressed else 'wylaczony'}{note}")

    if zapis_lock:
        with zapis_lock:
            ser.write(b"STATE?\n")
    else:
        ser.write(b"STATE?\n")
    last_rx = time.monotonic()

    while True:
        raw = ser.readline()  # na odlaczonym porcie rzuca SerialException
        now = time.monotonic()
        if not raw:
            if now - last_rx > SILENCE_TIMEOUT_S:
                raise ConnectionLost(f"brak danych z ESP32 od {SILENCE_TIMEOUT_S:.0f} s")
            continue
        last_rx = now

        parts = raw.decode("ascii", errors="ignore").strip().split()
        if not parts:
            continue

        if parts[0] == "BTN" and len(parts) >= 3:
            try:
                number = int(parts[1])
            except ValueError:
                continue
            apply(number, parts[2].upper() == "ON", parts[3] if len(parts) >= 4 else "")

        elif parts[0] == "STATE" and len(parts) >= 2:
            # Pelny stan co 1 s - naprawia ewentualnie zgubione komunikaty.
            for number, ch in enumerate(parts[1], start=1):
                if ch in "01":
                    apply(number, ch == "1", sync=True)


# ================================= main ====================================

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Kierownica GT: ESP32 -> wirtualny kontroler do gier")
    ap.add_argument("--port", help="konkretny port, np. COM5 (domyslnie: autowykrywanie)")
    ap.add_argument("--backend", choices=["auto", "vjoy", "xbox", "konsola"], default="auto",
                    help="rodzaj emulacji kontrolera (domyslnie: auto)")
    ap.add_argument("--vjoy-id", type=int, default=1, help="numer urzadzenia vJoy (domyslnie 1)")
    ap.add_argument("--list", action="store_true", help="wypisz porty COM i zakoncz")
    ap.add_argument("--bez-diod", action="store_true",
                    help="nie steruj paskiem LED (telemetria z gry wylaczona)")
    return ap.parse_args()


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    args = parse_args()

    if args.list:
        ports = list_candidate_ports()
        if not ports:
            print("Brak portow COM.")
        for p in ports:
            vid = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "----:----"
            print(f"{p.device:<12} {vid}  {p.description}")
        return

    print("=" * 60)
    print("  KIEROWNICA GT  -  ESP32 -> kontroler do gier")
    print("=" * 60)

    backend = create_backend(args.backend, args.vjoy_id)
    log(f"Emulacja: {backend.name}")
    czytnik = None if args.bez_diod else telemetria.Czytnik()

    try:
        while True:
            port, ser, info = wait_for_device(args.port)
            log(f"Polaczono z kierownica na porcie {port} ({info.n_buttons} przyciskow). Gotowe!")
            zapis_lock = threading.Lock()
            diody = None
            if czytnik is not None:
                if info.max_leds:
                    diody = DiodyZGry(ser, info.max_leds, czytnik, zapis_lock)
                    diody.start()
                else:
                    log("Firmware kierownicy nie obsluguje paska LED (wgraj wersje 1.1).")
            try:
                listen(ser, backend, info.n_buttons, zapis_lock)
            except (serial.SerialException, OSError, ConnectionLost) as exc:
                log(f"Utracono polaczenie z kierownica: {exc}")
            finally:
                if diody:
                    diody.zatrzymaj()
                backend.release_all()
                try:
                    ser.close()
                except Exception:
                    pass
            time.sleep(1.0)
    except KeyboardInterrupt:
        print()
        log("Zamykanie...")
    finally:
        backend.close()
        if czytnik is not None:
            czytnik.zamknij()


if __name__ == "__main__":
    main()
