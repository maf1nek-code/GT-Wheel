#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kierownica GT - konfigurator.

Program w tle obsluguje kierownice (port COM) i liczy efekty LED, a interfejs
jest strona w folderze pc/ui, otwierana w osobnym oknie (Microsoft Edge /
Chrome w trybie aplikacji, bez paskow przegladarki).

  * Test przyciskow - na zywo, na rysunku kierownicy.
  * Diody LED       - kolory, progi obrotow, efekty, podglad, profile.

Uruchomienie: Konfigurator_GT.bat  albo  python konfigurator.py [opcje]
  --port COM5        konkretny port (domyslnie: automatycznie)
  --bez-okna         nie otwieraj okna (adres wypisze sie w konsoli)
  --zostaw           nie koncz programu po zamknieciu okna

Port COM moze miec otwarty tylko jeden program - zamknij Kierownica_GT.bat
i Serial Monitor na czas konfiguracji.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    import serial
except ImportError:
    print("Brak biblioteki pyserial. Zainstaluj ja poleceniem:  pip install pyserial")
    sys.exit(1)

import led_efekty as fx
from kierownica import list_candidate_ports, probe

KATALOG = Path(__file__).resolve().parent
KATALOG_UI = KATALOG / "ui"
KATALOG_PROFILI = KATALOG / "profile_led"
PLIK_UKLADU = KATALOG / "uklad_kierownicy.json"   # ktory przycisk jest w ktorym miejscu rysunku
PREFEROWANY_PORT_HTTP = 47823

SILENCE_TIMEOUT_S = 5.0     # ESP wysyla STATE co 1 s - cisza = rozlaczenie
RETRY_S = 2.0               # co ile szukac kierownicy, gdy jej nie ma
FPS = 30
ZAMKNIJ_PO_S = 6.0          # bez otwartego okna przez tyle sekund -> koniec

TYPY_PLIKOW = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

STANY_SYMULACJI = ("jazda", "pit", "zolta", "niebieska", "brak_gry")
ZAREZERWOWANE_NAZWY = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)),
                       *(f"lpt{i}" for i in range(10))}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _json(dane) -> str:
    return json.dumps(dane, ensure_ascii=False, separators=(",", ":"))


def _klucz_ustawien(u: dict) -> str:
    return json.dumps(fx.popraw_ustawienia(u), sort_keys=True)


def _hex_paska(kolory: list) -> str:
    return "".join("{:02x}{:02x}{:02x}".format(*k) for k in kolory)


# ============================== stan programu ==============================

class Rozglosnia:
    """Lista otwartych okien (polaczen SSE) i wysylanie im wiadomosci."""

    def __init__(self) -> None:
        self._klienci: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.ostatnio_ktos = time.monotonic()
        self.byl_ktos = False

    def dodaj(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=600)
        with self._lock:
            self._klienci.append(q)
            self.byl_ktos = True
        return q

    def usun(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._klienci:
                self._klienci.remove(q)
            self.ostatnio_ktos = time.monotonic()

    @property
    def liczba(self) -> int:
        with self._lock:
            return len(self._klienci)

    def wyslij(self, wiad: dict, wazne: bool = True) -> None:
        tekst = _json(wiad)
        with self._lock:
            klienci = list(self._klienci)
        for q in klienci:
            try:
                if not wazne and q.qsize() > 60:
                    continue      # wolne okno - pomin klatke podgladu, nie zdarzenie
                q.put_nowait(tekst)
            except queue.Full:
                pass


class Aplikacja:
    def __init__(self, port: str | None) -> None:
        self.lock = threading.RLock()
        self.radio = Rozglosnia()
        self.koniec = threading.Event()

        # ustawienia LED
        self.blad_wczytania = None
        try:
            self.u = fx.wczytaj()
        except ValueError as exc:
            self.u = fx.domyslne_ustawienia()
            self.blad_wczytania = str(exc)
        self._zapisane = _klucz_ustawien(self.u)
        self.profil: str | None = None

        # symulacja w podgladzie
        self.sim = {"stan": "jazda", "obroty": 0.8, "auto": True, "wysylaj": True}
        self._t0 = time.monotonic()

        # kierownica
        self.port_wybrany = port
        self.chce_polaczenia = True
        self.gen = 0
        self.zmiana = threading.Event()
        self.ser = None
        self.info = None
        self.id_polaczenia = 0
        self.status = {"stan": "szukam", "tekst": "Szukam kierownicy…"}
        self.piny: dict[int, str] = {}
        self.bity = ""

        # wysylanie na pasek
        self._ser_lock = threading.Lock()
        self._ostatnia_linia = ""
        self._ostatnie_wyslanie = 0.0
        self._pasek_zapalony = False
        self.status_paska = "brak"

    # ------------------------------------------------------------- ustawienia
    @property
    def niezapisane(self) -> bool:
        return _klucz_ustawien(self.u) != self._zapisane

    def ustaw(self, nowe: dict) -> dict:
        with self.lock:
            self.u = fx.popraw_ustawienia(nowe)
            return self.u

    def zapisz(self) -> None:
        with self.lock:
            self.u = fx.popraw_ustawienia(self.u)
            fx.zapisz(self.u)
            self._zapisane = _klucz_ustawien(self.u)
            if self.profil:
                KATALOG_PROFILI.mkdir(exist_ok=True)
                fx.zapisz(self.u, self._plik_profilu(self.profil))

    def cofnij(self) -> None:
        with self.lock:
            self.u = fx.wczytaj() if fx.PLIK_USTAWIEN.exists() else fx.domyslne_ustawienia()

    # --------------------------------------------------------------- profile
    @staticmethod
    def popraw_nazwe(nazwa) -> str:
        nazwa = re.sub(r"\s+", " ", str(nazwa)).strip()
        if not nazwa or len(nazwa) > 40 or not re.fullmatch(r"[\w .\-()]+", nazwa):
            raise ValueError("Nazwa profilu: do 40 znaków - litery, cyfry, spacje i - _ . ( )")
        if nazwa.startswith(".") or nazwa.endswith(".") \
                or nazwa.split(".")[0].strip().lower() in ZAREZERWOWANE_NAZWY:
            raise ValueError("Tej nazwy nie da się użyć jako nazwy pliku. Wybierz inną.")
        return nazwa

    def _plik_profilu(self, nazwa: str) -> Path:
        return KATALOG_PROFILI / f"{self.popraw_nazwe(nazwa)}.json"

    def profile(self) -> list[dict]:
        if not KATALOG_PROFILI.exists():
            return []
        wynik = []
        for p in sorted(KATALOG_PROFILI.glob("*.json"), key=lambda x: x.stem.lower()):
            try:
                u = fx.wczytaj(p)
                wynik.append({"nazwa": p.stem, "kolory": u["kolory"], "liczba": u["liczba_diod"]})
            except (ValueError, OSError):
                wynik.append({"nazwa": p.stem, "kolory": [], "liczba": 0, "blad": True})
        return wynik

    # --------------------------------------------------------- uklad rysunku
    @staticmethod
    def wczytaj_uklad() -> dict | None:
        try:
            dane = json.loads(PLIK_UKLADU.read_text(encoding="utf-8"))
            return Aplikacja.popraw_uklad(dane.get("miejsca", {}))
        except (OSError, ValueError, AttributeError):
            return None

    @staticmethod
    def popraw_uklad(miejsca) -> dict:
        if not isinstance(miejsca, dict):
            raise ValueError("Zły układ przycisków.")
        wynik: dict[str, int] = {}
        for k, v in miejsca.items():
            if not isinstance(k, str) or not re.fullmatch(r"[a-z_]{1,30}", k):
                raise ValueError("Zła nazwa miejsca.")
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 64:
                continue
            if v not in wynik.values():
                wynik[k] = v
        return wynik

    # ------------------------------------------------------------- migawka
    def migawka(self) -> dict:
        with self.lock:
            return {
                "t": "witaj",
                "ustawienia": self.u,
                "niezapisane": self.niezapisane,
                "profil": self.profil,
                "profile": self.profile(),
                "plik": str(fx.PLIK_USTAWIEN),
                "sim": self.sim,
                "status": self._status_dane(),
                "piny": self.piny,
                "bity": self.bity,
                "blad": self.blad_wczytania,
                "uklad": self.wczytaj_uklad(),
                "opcje": {
                    "kierunki": fx.KIERUNKI,
                    "wzory_pit": fx.WZORY_PIT,
                    "tryby": fx.TRYBY_BEZCZYNNOSCI,
                    "presety": fx.PRESETY,
                    "max_diod": fx.MAX_DIOD,
                },
            }

    def wyslij_ustawienia(self) -> None:
        with self.lock:
            self.radio.wyslij({"t": "ustawienia", "ustawienia": self.u,
                               "niezapisane": self.niezapisane, "profil": self.profil,
                               "profile": self.profile()})

    # ============================ kierownica ==============================
    def _status_dane(self) -> dict:
        d = dict(self.status)
        d["port_wybrany"] = self.port_wybrany
        d["chce"] = self.chce_polaczenia
        d["id"] = self.id_polaczenia
        if self.info is not None and d.get("stan") == "polaczono":
            d["info"] = {"przyciski": self.info.n_buttons, "wersja": self.info.version,
                         "max_diod": self.info.max_leds}
        return d

    def _ustaw_status(self, stan: str, tekst: str, **dodatkowe) -> None:
        with self.lock:
            self.status = {"stan": stan, "tekst": tekst, **dodatkowe}
            self.radio.wyslij({"t": "status", "status": self._status_dane()})

    def polacz(self, port: str | None) -> None:
        with self.lock:
            self.port_wybrany = port or None
            self.chce_polaczenia = True
            self.gen += 1
        self.zmiana.set()

    def rozlacz(self) -> None:
        with self.lock:
            self.chce_polaczenia = False
            self.gen += 1
        self.zmiana.set()

    def wyslij_do_kierownicy(self, linia: str) -> bool:
        with self._ser_lock:
            if self.ser is None:
                return False
            try:
                self.ser.write((linia + "\n").encode("ascii"))
                return True
            except (serial.SerialException, OSError):
                return False

    def watek_kierownicy(self) -> None:
        while not self.koniec.is_set():
            with self.lock:
                gen, chce, port = self.gen, self.chce_polaczenia, self.port_wybrany
            if not chce:
                if self.status.get("stan") != "rozlaczono":
                    self._ustaw_status("rozlaczono", "Rozłączono.")
                self.zmiana.wait(0.5)
                self.zmiana.clear()
                continue

            self._ustaw_status("szukam", f"Łączę z {port}…" if port else "Szukam kierownicy…")
            nazwy = [port] if port else [p.device for p in list_candidate_ports()]
            zajete: list[str] = []
            znalezione = None
            for nazwa in nazwy:
                if self.koniec.is_set() or gen != self.gen:
                    break
                wynik = probe(nazwa, zajete)
                if wynik:
                    znalezione = (nazwa, *wynik)
                    break

            if gen != self.gen or self.koniec.is_set():
                if znalezione:
                    znalezione[1].close()
                continue

            if not znalezione:
                if zajete:
                    tekst = (f"Port {', '.join(zajete)} jest zajęty przez inny program. Zamknij "
                             "Kierownica_GT.bat albo Serial Monitor.")
                    self._ustaw_status("zajety", tekst, zajete=zajete)
                elif not nazwy:
                    self._ustaw_status("brak", "Nie widzę żadnego portu COM. Podłącz kierownicę "
                                               "kablem USB.")
                else:
                    self._ustaw_status("brak", "Nie znaleziono kierownicy na portach: "
                                       + ", ".join(nazwy) + ".")
                self.zmiana.wait(RETRY_S)
                self.zmiana.clear()
                continue

            nazwa, ser, info = znalezione
            with self._ser_lock:
                self.ser = ser
            with self.lock:
                self.info = info
                self.id_polaczenia += 1
                self.piny = {}
                self.bity = ""
                self._ostatnia_linia = ""
            self._ustaw_status("polaczono", f"Połączono ({nazwa})", port=nazwa)
            log(f"Polaczono z kierownica na porcie {nazwa} (firmware {info.version}, "
                f"{info.n_buttons} przyciskow, LED: {info.max_leds or 'brak'}).")
            self.wyslij_do_kierownicy("INFO")
            self.wyslij_do_kierownicy("STATE?")

            powod = self._czytaj(ser, gen)

            if self._pasek_zapalony:
                self.wyslij_do_kierownicy("LEDS")
            with self._ser_lock:
                self.ser = None
                try:
                    ser.close()
                except Exception:
                    pass
            with self.lock:
                self.info = None
                self._pasek_zapalony = False
            if powod:
                log(f"Utracono polaczenie: {powod}")
                self._ustaw_status("utracono", f"Utracono połączenie ({powod}). Szukam ponownie…")
                self.zmiana.wait(1.0)
                self.zmiana.clear()

    def _czytaj(self, ser, gen: int) -> str | None:
        """Czyta port do rozlaczenia. Zwraca powod utraty albo None (rozlaczone celowo)."""
        ostatnio = time.monotonic()
        piny_info: dict[int, str] = {}
        try:
            while not self.koniec.is_set() and gen == self.gen:
                raw = ser.readline()
                teraz = time.monotonic()
                if not raw:
                    if teraz - ostatnio > SILENCE_TIMEOUT_S:
                        return f"brak danych od {SILENCE_TIMEOUT_S:.0f} s"
                    continue
                ostatnio = teraz
                cz = raw.decode("ascii", errors="ignore").strip().split()
                if not cz:
                    continue
                if cz[0] == "BTN" and len(cz) >= 3 and cz[1].isdigit():
                    numer = int(cz[1])
                    pin = cz[3] if len(cz) >= 4 else ""
                    wl = cz[2].upper() == "ON"
                    with self.lock:
                        if pin:
                            self.piny[numer] = pin
                        if 1 <= numer <= len(self.bity):
                            b = list(self.bity)
                            b[numer - 1] = "1" if wl else "0"
                            self.bity = "".join(b)
                    self.radio.wyslij({"t": "przycisk", "n": numer, "wl": wl, "pin": pin})
                elif cz[0] == "STATE" and len(cz) >= 2:
                    with self.lock:
                        self.bity = cz[1]
                    self.radio.wyslij({"t": "stan", "bity": cz[1]})
                elif cz[0] == "INFO" and len(cz) >= 5 and cz[1] == "BTN" and cz[2].isdigit() \
                        and cz[3] == "PIN":
                    piny_info[int(cz[2])] = cz[4]
                    info = self.info
                    if info and len(piny_info) >= info.n_buttons:
                        with self.lock:
                            self.piny.update(piny_info)
                            self.radio.wyslij({"t": "piny", "piny": self.piny})
                        piny_info = {}
        except (serial.SerialException, OSError) as exc:
            return str(exc) or "port zamknięty"
        return None

    # ============================== animacja ===============================
    @staticmethod
    def _telemetria(stan: str, obroty: float) -> fx.Telemetria:
        return fx.Telemetria(
            obroty=obroty,
            gra_aktywna=stan != "brak_gry",
            pit_limiter=stan == "pit",
            flaga={"zolta": "zolta", "niebieska": "niebieska"}.get(stan),
        )

    def watek_animacji(self) -> None:
        krok = 1.0 / FPS
        nastepna = time.monotonic()
        while not self.koniec.is_set():
            nastepna += krok
            try:
                self._klatka()
            except Exception as exc:  # nie zatrzymuj podgladu przez jeden blad
                log(f"Blad podgladu: {exc!r}")
            opoznienie = nastepna - time.monotonic()
            if opoznienie > 0:
                time.sleep(opoznienie)
            else:
                nastepna = time.monotonic()

    def _klatka(self) -> None:
        t = time.monotonic() - self._t0
        with self.lock:
            u = fx.popraw_ustawienia(self.u)
            if self.sim["auto"]:
                cykl = t % 4.5
                self.sim["obroty"] = (min(1.0, 0.45 + 0.57 * (cykl / 3.5) ** 1.3)
                                      if cykl < 3.5 else 1.0)
            sim = dict(self.sim)

        glowna = fx.klatka(u, self._telemetria(sim["stan"], sim["obroty"]), t)
        mini = {
            "zmiana_biegu": fx.klatka(u, self._telemetria("jazda", 1.0), t),
            "pit_limiter": fx.klatka(u, self._telemetria("pit", 0.5), t),
            "flaga_zolta": fx.klatka(u, self._telemetria("zolta", 0.75), t),
            "flaga_niebieska": fx.klatka(u, self._telemetria("niebieska", 0.75), t),
            "brak_gry": fx.klatka(u, self._telemetria("brak_gry", 0.0), t),
        }
        self._na_pasek(glowna, u, sim)
        self.radio.wyslij({
            "t": "klatka",
            "glowna": _hex_paska(glowna),
            "obroty": round(sim["obroty"], 4),
            "mini": {k: _hex_paska(v) for k, v in mini.items()},
            "pasek": self.status_paska,
        }, wazne=False)

    def _na_pasek(self, kolory: list, u: dict, sim: dict) -> None:
        info = self.info
        if self.ser is None or info is None:
            self.status_paska = "brak"
            return
        if info.max_leds == 0:
            self.status_paska = "bez_led"
            return
        if not sim["wysylaj"]:
            if self._pasek_zapalony:
                self.wyslij_do_kierownicy("LEDS")
                self._pasek_zapalony = False
                self._ostatnia_linia = ""
            self.status_paska = "wylaczony"
            return

        linia = fx.komenda_leds(fx.z_jasnoscia(kolory[:info.max_leds], u["jasnosc"]))
        teraz = time.monotonic()
        # ~70% przepustowosci 115200 bodow: przy 60 diodach ok. 20 klatek/s
        if teraz - self._ostatnie_wyslanie < max(1.0 / FPS, len(linia) / 8000.0):
            return
        if linia == self._ostatnia_linia and teraz - self._ostatnie_wyslanie < 1.0:
            return
        if self.wyslij_do_kierownicy(linia):
            self._ostatnia_linia = linia
            self._ostatnie_wyslanie = teraz
            self._pasek_zapalony = True
            self.status_paska = "wysylam"

    def zamknij(self) -> None:
        self.koniec.set()
        self.zmiana.set()
        if self._pasek_zapalony:
            self.wyslij_do_kierownicy("LEDS")


# ================================ HTTP =====================================

class BladZapytania(Exception):
    pass


def _liczba_diod(d: dict) -> int:
    try:
        n = int(d.get("n", 16))
    except (TypeError, ValueError) as exc:
        raise BladZapytania("Zła liczba diod.") from exc
    if not 1 <= n <= fx.MAX_DIOD:
        raise BladZapytania("Zła liczba diod.")
    return n


def _kierunek(d: dict) -> str:
    kierunek = d.get("kierunek", "lewo_prawo")
    if kierunek not in fx.KIERUNKI:
        raise BladZapytania("Zły kierunek.")
    return kierunek


def stworz_obsluge(app: Aplikacja, port_http: list):
    class Obsluga(BaseHTTPRequestHandler):
        server_version = "KierownicaGT"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # bez zasmiecania konsoli
            pass

        # ---------------------------------------------------------- pomocnicze
        def _host_ok(self) -> bool:
            # chroni przed stronami z internetu, ktore probowalyby sterowac konfiguratorem
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_http[0]}", f"localhost:{port_http[0]}")

        def _odpowiedz(self, kod: int, tresc: bytes, typ: str) -> None:
            self.send_response(kod)
            self.send_header("Content-Type", typ)
            self.send_header("Content-Length", str(len(tresc)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(tresc)

        def _json(self, dane, kod: int = 200) -> None:
            self._odpowiedz(kod, _json(dane).encode("utf-8"), "application/json; charset=utf-8")

        def _cialo(self) -> dict:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise BladZapytania("Oczekiwano JSON.")
            try:
                dlugosc = int(self.headers.get("Content-Length") or 0)
            except ValueError as exc:
                raise BladZapytania("Zła długość.") from exc
            if not 0 <= dlugosc <= 1_000_000:
                raise BladZapytania("Za duże zapytanie.")
            try:
                dane = json.loads(self.rfile.read(dlugosc) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise BladZapytania(f"Niepoprawny JSON: {exc}") from exc
            if not isinstance(dane, dict):
                raise BladZapytania("Oczekiwano obiektu JSON.")
            return dane

        # ------------------------------------------------------------- GET
        def do_GET(self) -> None:
            if not self._host_ok():
                self._odpowiedz(403, b"Forbidden", "text/plain")
                return
            sciezka = urlsplit(self.path).path
            if sciezka == "/api/zdarzenia":
                self._sse()
                return
            if sciezka == "/api/porty":
                porty = [{"port": p.device, "opis": p.description or ""}
                         for p in list_candidate_ports()]
                self._json({"ok": True, "porty": porty})
                return
            if sciezka == "/":
                sciezka = "/index.html"
            plik = (KATALOG_UI / sciezka.lstrip("/")).resolve()
            if KATALOG_UI.resolve() not in plik.parents or not plik.is_file() \
                    or plik.suffix not in TYPY_PLIKOW:
                self._odpowiedz(404, "Nie ma takiej strony".encode(), "text/plain; charset=utf-8")
                return
            self._odpowiedz(200, plik.read_bytes(), TYPY_PLIKOW[plik.suffix])

        def do_HEAD(self) -> None:
            self.do_GET()

        def _sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = app.radio.dodaj()
            try:
                self.wfile.write(f"retry: 1000\ndata: {_json(app.migawka())}\n\n".encode("utf-8"))
                self.wfile.flush()
                while not app.koniec.is_set():
                    try:
                        porcja = f"data: {q.get(timeout=10)}\n\n"
                    except queue.Empty:
                        porcja = ": ping\n\n"
                    self.wfile.write(porcja.encode("utf-8"))
                    self.wfile.flush()
            except OSError:   # okno zamkniete / odswiezone
                pass
            finally:
                app.radio.usun(q)
                self.close_connection = True

        # ------------------------------------------------------------ POST
        def do_POST(self) -> None:
            if not self._host_ok():
                self._odpowiedz(403, b"Forbidden", "text/plain")
                return
            sciezka = urlsplit(self.path).path
            try:
                dane = self._cialo()
                wynik = self._akcja(sciezka, dane)
            except (BladZapytania, ValueError, TypeError) as exc:
                self._json({"ok": False, "blad": str(exc)}, 400)
                return
            except OSError as exc:
                self._json({"ok": False, "blad": f"Błąd zapisu pliku: {exc}"}, 500)
                return
            if wynik is None:
                self._json({"ok": False, "blad": "Nieznana akcja."}, 404)
                return
            self._json({"ok": True, **wynik})

        def _akcja(self, sciezka: str, d: dict) -> dict | None:
            if sciezka == "/api/ustawienia":
                if not isinstance(d.get("ustawienia"), dict):
                    raise BladZapytania("Brak ustawień.")
                with app.lock:
                    app.ustaw(d["ustawienia"])
                    wynik = {"ustawienia": app.u, "niezapisane": app.niezapisane}
                if d.get("rozglos"):
                    app.wyslij_ustawienia()
                else:
                    app.radio.wyslij({"t": "niezapisane", "niezapisane": wynik["niezapisane"]})
                return wynik

            if sciezka == "/api/sim":
                with app.lock:
                    if d.get("stan") in STANY_SYMULACJI:
                        app.sim["stan"] = d["stan"]
                    if "obroty" in d:
                        app.sim["obroty"] = min(1.0, max(0.0, float(d["obroty"])))
                        app.sim["auto"] = False
                    for klucz in ("auto", "wysylaj"):
                        if klucz in d:
                            app.sim[klucz] = bool(d[klucz])
                    sim = dict(app.sim)
                app.radio.wyslij({"t": "sim", "sim": sim})
                return {"sim": sim}

            if sciezka == "/api/zapisz":
                app.zapisz()
                app.wyslij_ustawienia()
                return {"plik": str(fx.PLIK_USTAWIEN)}

            if sciezka == "/api/cofnij":
                app.cofnij()
                app.wyslij_ustawienia()
                return {}

            if sciezka == "/api/domyslne":
                with app.lock:
                    app.u = fx.domyslne_ustawienia()
                app.wyslij_ustawienia()
                return {}

            if sciezka == "/api/presety":
                n, kierunek = _liczba_diod(d), _kierunek(d)
                return {"presety": {k: [fx.kolor_na_hex(c)
                                        for c in fx.kolory_presetu(k, n, kierunek)]
                                    for k in fx.PRESETY}}

            if sciezka == "/api/gradient":
                n, kierunek = _liczba_diod(d), _kierunek(d)
                punkty = [fx.hex_na_kolor(k) for k in d.get("punkty") or []]
                if len(punkty) < 2:
                    raise BladZapytania("Gradient potrzebuje co najmniej 2 kolorów.")
                return {"kolory": [fx.kolor_na_hex(c)
                                   for c in fx.kolory_gradient(n, kierunek, punkty)]}

            if sciezka == "/api/polacz":
                port = d.get("port") or None
                if port is not None and (not isinstance(port, str) or len(port) > 200):
                    raise BladZapytania("Zły port.")
                app.polacz(port)
                return {}

            if sciezka == "/api/uklad":
                if d.get("domyslny"):
                    if PLIK_UKLADU.exists():
                        PLIK_UKLADU.unlink()
                    uklad = None
                else:
                    uklad = app.popraw_uklad(d.get("miejsca"))
                    tmp = PLIK_UKLADU.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"miejsca": uklad}, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
                    tmp.replace(PLIK_UKLADU)
                app.radio.wyslij({"t": "uklad", "uklad": uklad})
                return {"uklad": uklad}

            if sciezka == "/api/rozlacz":
                app.rozlacz()
                return {}

            if sciezka == "/api/profile/zapisz":
                nazwa = app.popraw_nazwe(d.get("nazwa", ""))
                KATALOG_PROFILI.mkdir(exist_ok=True)
                with app.lock:
                    fx.zapisz(app.u, app._plik_profilu(nazwa))
                    app.profil = nazwa
                app.wyslij_ustawienia()
                return {"nazwa": nazwa}

            if sciezka == "/api/profile/wczytaj":
                nazwa = app.popraw_nazwe(d.get("nazwa", ""))
                plik = app._plik_profilu(nazwa)
                if not plik.exists():
                    raise BladZapytania("Nie ma takiego profilu.")
                with app.lock:
                    app.u = fx.wczytaj(plik)
                    app.profil = nazwa
                app.wyslij_ustawienia()
                return {}

            if sciezka == "/api/profile/usun":
                nazwa = app.popraw_nazwe(d.get("nazwa", ""))
                plik = app._plik_profilu(nazwa)
                if plik.exists():
                    plik.unlink()
                with app.lock:
                    if app.profil == nazwa:
                        app.profil = None
                app.wyslij_ustawienia()
                return {}

            return None

    return Obsluga


# ============================= okno programu ===============================

def znajdz_przegladarke() -> str | None:
    """Edge albo Chrome - potrafia otworzyc strone jako osobne okno aplikacji."""
    kandydaci: list[Path] = []
    if sys.platform == "win32":
        for zmienna in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            baza = os.environ.get(zmienna)
            if baza:
                kandydaci += [Path(baza) / "Microsoft/Edge/Application/msedge.exe",
                              Path(baza) / "Google/Chrome/Application/chrome.exe"]
    for nazwa in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser",
                  "chrome"):
        sciezka = shutil.which(nazwa)
        if sciezka:
            kandydaci.append(Path(sciezka))
    for k in kandydaci:
        if k.is_file():
            return str(k)
    return None


def otworz_okno(adres: str) -> None:
    przegladarka = znajdz_przegladarke()
    if przegladarka:
        if sys.platform == "win32":
            profil = Path(os.environ.get("LOCALAPPDATA", str(KATALOG))) / "KierownicaGT" / "okno"
        else:
            profil = Path.home() / ".cache" / "kierownica_gt_okno"
        try:
            subprocess.Popen([przegladarka, f"--app={adres}", f"--user-data-dir={profil}",
                              "--window-size=1440,920", "--no-first-run",
                              "--no-default-browser-check"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(adres)


def wolny_port() -> int:
    for port in (PREFEROWANY_PORT_HTTP, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("Brak wolnego portu")


def main() -> None:
    ap = argparse.ArgumentParser(description="Kierownica GT - konfigurator")
    ap.add_argument("--port", help="konkretny port, np. COM5 (domyślnie: automatycznie)")
    ap.add_argument("--bez-okna", action="store_true", help="nie otwieraj okna")
    ap.add_argument("--zostaw", action="store_true", help="nie kończ po zamknięciu okna")
    ap.add_argument("--http", type=int, default=0, help="port serwera (domyślnie automatycznie)")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    app = Aplikacja(args.port)
    port_http = [args.http or wolny_port()]
    serwer = ThreadingHTTPServer(("127.0.0.1", port_http[0]), stworz_obsluge(app, port_http))
    serwer.daemon_threads = True
    adres = f"http://127.0.0.1:{port_http[0]}/"

    threading.Thread(target=app.watek_kierownicy, daemon=True).start()
    threading.Thread(target=app.watek_animacji, daemon=True).start()

    def straznik() -> None:
        """Konczy program, gdy okno zostalo zamkniete."""
        start = time.monotonic()
        while not app.koniec.is_set():
            time.sleep(1.0)
            if args.zostaw or app.radio.liczba > 0:
                continue
            odkad = app.radio.ostatnio_ktos if app.radio.byl_ktos else start
            limit = ZAMKNIJ_PO_S if app.radio.byl_ktos else 120.0
            if time.monotonic() - odkad > limit:
                log("Okno zamkniete - koncze.")
                serwer.shutdown()
                return

    threading.Thread(target=straznik, daemon=True).start()

    print("=" * 60)
    print("  KIEROWNICA GT  -  konfigurator")
    print("=" * 60)
    log(f"Okno konfiguratora: {adres}")
    log("Zamknij okno konfiguratora, aby zakonczyc (albo Ctrl+C tutaj).")
    if not args.bez_okna:
        otworz_okno(adres)

    try:
        serwer.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        app.zamknij()
        serwer.server_close()
        time.sleep(0.2)
        log("Zakonczono.")


if __name__ == "__main__":
    main()
