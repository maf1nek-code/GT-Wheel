#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kierownica GT - konfigurator (okienko na PC).

Zakladki:
  1. Test przyciskow - pokazuje na zywo, ktore przyciski dzialaja.
  2. Diody LED       - kolory, progi obrotow, efekty (zmiana biegu, pit limiter,
                       flagi, brak gry) z podgladem i symulacja; ustawienia
                       zapisywane do pc/leds.json.

Uruchomienie: Konfigurator_GT.bat albo  python konfigurator.py [--port COM5]

Uwaga: port COM moze miec otwarty tylko jeden program. Gdy dziala
Kierownica_GT.bat (albo Serial Monitor w Arduino IDE), zamknij go na czas
konfiguracji.
"""

from __future__ import annotations

import argparse
import math
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk
    import tkinter.font as tkfont
except ImportError:
    print("Brak biblioteki tkinter. Zainstaluj Pythona z python.org (tkinter jest w zestawie).")
    sys.exit(1)

try:
    import serial
except ImportError:
    print("Brak biblioteki pyserial. Zainstaluj ja poleceniem:  pip install pyserial")
    sys.exit(1)

import led_efekty as fx
from kierownica import DeviceInfo, list_candidate_ports, probe

SILENCE_TIMEOUT_S = 5.0      # ESP wysyla STATE co 1 s - cisza = rozlaczenie
RETRY_S = 2.0                # co ile szukac kierownicy, gdy jej nie ma
FPS = 30
AUTO = "Automatycznie"

# Kolory interfejsu
KOLOR_TLO_PASKA = "#15181d"
KOLOR_DIODA_OFF = "#2a2e35"
KAFEL_NIESPRAWDZONY = "#3a3f47"
KAFEL_SPRAWDZONY = "#1d5a37"
KAFEL_WCISNIETY = "#2ecc71"
KAFEL_PODEJRZANY = "#9a6200"


# ============================ polaczenie ===================================

class Polaczenie:
    """Laczenie i czytanie portu w osobnym watku. Wyniki trafiaja do kolejki."""

    def __init__(self, kolejka: queue.Queue) -> None:
        self.q = kolejka
        self.ser = None
        self.port: str | None = None
        self.info: DeviceInfo | None = None
        self._lock = threading.Lock()
        self._gen = 0
        self._stop = threading.Event()
        self._watek: threading.Thread | None = None

    @property
    def polaczony(self) -> bool:
        return self.ser is not None

    def polacz(self, port: str | None) -> int:
        self.rozlacz()
        self._gen += 1
        self._stop = threading.Event()
        self._watek = threading.Thread(target=self._praca, args=(self._gen, port, self._stop),
                                       daemon=True)
        self._watek.start()
        return self._gen

    def _praca(self, gen: int, port: str | None, stop: threading.Event) -> None:
        nazwy = [port] if port else [p.device for p in list_candidate_ports()]
        zajete: list[str] = []
        wynik = None
        for nazwa in nazwy:
            if stop.is_set():
                return
            wynik = probe(nazwa, zajete)
            if wynik:
                port = nazwa
                break
        if not wynik:
            self.q.put(("brak", gen, zajete, nazwy))
            return

        ser, info = wynik
        if stop.is_set():
            ser.close()
            return
        with self._lock:
            self.ser, self.port, self.info = ser, port, info
        self.q.put(("polaczono", gen, port, info))

        ostatnio = time.monotonic()
        powod = None
        try:
            while not stop.is_set():
                raw = ser.readline()
                teraz = time.monotonic()
                if raw:
                    ostatnio = teraz
                    tekst = raw.decode("ascii", errors="ignore").strip()
                    if tekst:
                        self.q.put(("linia", gen, tekst))
                elif teraz - ostatnio > SILENCE_TIMEOUT_S:
                    powod = f"brak danych od {SILENCE_TIMEOUT_S:.0f} s"
                    break
        except (serial.SerialException, OSError) as exc:
            powod = str(exc) or "port zamknięty"

        with self._lock:
            if self.ser is ser:
                self.ser = None
            try:
                ser.close()
            except Exception:
                pass
        if not stop.is_set():
            self.q.put(("utracono", gen, powod or "rozłączono"))

    def wyslij(self, linia: str) -> bool:
        with self._lock:
            if self.ser is None:
                return False
            try:
                self.ser.write((linia + "\n").encode("ascii"))
                return True
            except (serial.SerialException, OSError):
                return False

    def rozlacz(self) -> None:
        self._stop.set()
        if self.ser is not None:
            self.wyslij("LEDS")   # zgas pasek przed odlaczeniem
            if self._watek is not None:
                self._watek.join(timeout=1.0)   # watek czytajacy konczy sie po <0.2 s
        with self._lock:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None
        self.info = None


# ============================ elementy UI ==================================

class Przewijany(ttk.Frame):
    """Ramka z pionowym paskiem przewijania (na dlugie ustawienia)."""

    def __init__(self, master, **kw) -> None:
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.pasek = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.wnetrze = ttk.Frame(self.canvas)
        self._okno = self.canvas.create_window((0, 0), window=self.wnetrze, anchor="nw")
        self.canvas.configure(yscrollcommand=self.pasek.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.pasek.pack(side="right", fill="y")
        self.wnetrze.bind("<Configure>",
                          lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._okno, width=e.width))
        for zdarzenie in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(zdarzenie, self._przewin, add="+")
            # Kolko nad lista rozwijana/polem liczbowym przewija ustawienia,
            # zamiast niechcacy zmieniac ich wartosc.
            for klasa in ("TCombobox", "TSpinbox"):
                self.bind_class(klasa, zdarzenie, lambda e: None)

    def _przewin(self, e) -> None:
        pod = self.winfo_containing(e.x_root, e.y_root)
        if pod is None or not str(pod).startswith(str(self)):
            return
        if self.canvas.yview() == (0.0, 1.0):
            return
        if getattr(e, "num", None) == 4:
            krok = -2
        elif getattr(e, "num", None) == 5:
            krok = 2
        else:
            krok = -2 if e.delta > 0 else 2
        self.canvas.yview_scroll(krok, "units")


class PolePrzycisku:
    """Stan jednego przycisku w testerze."""

    def __init__(self, numer: int) -> None:
        self.numer = numer
        self.pin = "?"
        self.wcisniety = False
        self.licznik = 0
        self.sprawdzony = False
        self.podejrzany = False   # wcisniety juz w chwili polaczenia (zwarcie?)
        self.od_kiedy = 0.0


def wybor_kolor(rodzic, kolor: str, tytul: str) -> str | None:
    wynik = colorchooser.askcolor(color=kolor, title=tytul, parent=rodzic)
    if not wynik or not wynik[1]:
        return None
    return fx.kolor_na_hex(fx.hex_na_kolor(wynik[1]))


class Probka(tk.Label):
    """Kwadracik z kolorem - klik otwiera wybor koloru."""

    def __init__(self, master, kolor: str, przy_zmianie, tytul: str = "Wybierz kolor") -> None:
        super().__init__(master, width=4, relief="ridge", borderwidth=2, cursor="hand2")
        self._przy_zmianie = przy_zmianie
        self._tytul = tytul
        self.ustaw(kolor)
        self.bind("<Button-1>", self._klik)

    def ustaw(self, kolor: str) -> None:
        self.kolor = kolor
        self.configure(bg=kolor, activebackground=kolor)

    def _klik(self, _e=None) -> None:
        nowy = wybor_kolor(self, self.kolor, self._tytul)
        if nowy:
            self.ustaw(nowy)
            self._przy_zmianie(nowy)


# ========================== zakladka: przyciski ============================

class ZakladkaPrzyciski(ttk.Frame):
    KOLUMNY = 6

    def __init__(self, master) -> None:
        super().__init__(master, padding=12)
        self.pola: list[PolePrzycisku] = []
        self.kafle: list[dict] = []
        self._pierwszy_stan = True

        baza = tkfont.nametofont("TkDefaultFont")
        self.f_numer = baza.copy()
        self.f_numer.configure(size=22, weight="bold")
        self.f_maly = baza.copy()
        self.f_maly.configure(size=max(8, baza.cget("size") - 1))

        ttk.Label(self, text="Wciśnij po kolei każdy przycisk na kierownicy. Wciśnięty kafelek "
                  "świeci na zielono, a sprawdzony dostaje znaczek ✓.",
                  wraplength=900).pack(anchor="w")

        gora = ttk.Frame(self)
        gora.pack(fill="x", pady=(10, 6))
        self.etykieta_postepu = ttk.Label(gora, text="")
        self.etykieta_postepu.pack(side="left")
        self.postep = ttk.Progressbar(gora, length=260, mode="determinate")
        self.postep.pack(side="left", padx=10)
        ttk.Button(gora, text="Zacznij test od nowa", command=self.reset).pack(side="right")

        self.siatka = ttk.Frame(self)
        self.siatka.pack(fill="x", pady=6)

        self.komunikat = ttk.Label(self, text="", foreground="#b05000")
        self.komunikat.pack(anchor="w", pady=(4, 0))

        dol = ttk.LabelFrame(self, text="Dziennik zdarzeń", padding=6)
        dol.pack(fill="both", expand=True, pady=(8, 0))
        self.dziennik = tk.Listbox(dol, height=8, activestyle="none")
        sb = ttk.Scrollbar(dol, orient="vertical", command=self.dziennik.yview)
        self.dziennik.configure(yscrollcommand=sb.set)
        self.dziennik.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.ustaw_liczbe(12)
        self.rozlaczono()

    # ---- budowa ----
    def ustaw_liczbe(self, n: int) -> None:
        if n == len(self.pola):
            return
        for w in self.siatka.winfo_children():
            w.destroy()
        self.pola = [PolePrzycisku(i + 1) for i in range(n)]
        self.kafle = []
        for i in range(self.KOLUMNY):
            self.siatka.columnconfigure(i, weight=1, uniform="kafel")
        for i, pole in enumerate(self.pola):
            ramka = tk.Frame(self.siatka, bg=KAFEL_NIESPRAWDZONY, height=118)
            ramka.grid(row=i // self.KOLUMNY, column=i % self.KOLUMNY, padx=4, pady=4, sticky="nsew")
            ramka.grid_propagate(False)
            ramka.pack_propagate(False)
            numer = tk.Label(ramka, text=str(pole.numer), font=self.f_numer)
            numer.pack(pady=(8, 0))
            pin = tk.Label(ramka, text="pin ?", font=self.f_maly)
            pin.pack()
            stan = tk.Label(ramka, text="", font=self.f_maly)
            stan.pack()
            licz = tk.Label(ramka, text="", font=self.f_maly)
            licz.pack()
            self.kafle.append({"ramka": ramka, "numer": numer, "pin": pin, "stan": stan, "licz": licz})
            self._rysuj(i)
        self._postep()

    def _rysuj(self, i: int) -> None:
        pole, k = self.pola[i], self.kafle[i]
        if pole.wcisniety and pole.podejrzany:
            bg, fg, stan = KAFEL_PODEJRZANY, "white", "wciśnięty od startu?"
        elif pole.wcisniety:
            bg, fg, stan = KAFEL_WCISNIETY, "black", "WCIŚNIĘTY"
        elif pole.sprawdzony:
            bg, fg, stan = KAFEL_SPRAWDZONY, "white", "✓ działa"
        else:
            bg, fg, stan = KAFEL_NIESPRAWDZONY, "#d0d4da", "nie sprawdzony"
        k["ramka"].configure(bg=bg)
        for nazwa in ("numer", "pin", "stan", "licz"):
            k[nazwa].configure(bg=bg, fg=fg)
        k["pin"].configure(text=f"pin {pole.pin}")
        k["stan"].configure(text=stan)
        k["licz"].configure(text=f"wciśnięć: {pole.licznik}")

    def _postep(self) -> None:
        n = len(self.pola)
        ok = sum(p.sprawdzony for p in self.pola)
        self.etykieta_postepu.configure(
            text=f"Sprawdzone: {ok} / {n}" + ("   ✓ wszystkie przyciski działają!" if ok == n else ""))
        self.postep.configure(maximum=n, value=ok)

    def _log(self, tekst: str) -> None:
        self.dziennik.insert("end", f"{datetime.now():%H:%M:%S}   {tekst}")
        if self.dziennik.size() > 300:
            self.dziennik.delete(0, self.dziennik.size() - 301)
        self.dziennik.see("end")

    # ---- zdarzenia z kierownicy ----
    def polaczono(self, info: DeviceInfo) -> None:
        self.ustaw_liczbe(info.n_buttons)
        self._pierwszy_stan = True
        self.komunikat.configure(text="")
        self._log(f"Połączono z kierownicą ({info.n_buttons} przycisków).")

    def rozlaczono(self) -> None:
        for i, pole in enumerate(self.pola):
            pole.wcisniety = False
            self._rysuj(i)
        self.komunikat.configure(text="Brak połączenia z kierownicą - podłącz ją kablem USB.")

    def ustaw_pin(self, numer: int, pin: str) -> None:
        if 1 <= numer <= len(self.pola):
            self.pola[numer - 1].pin = pin
            self._rysuj(numer - 1)

    def zmiana(self, numer: int, wcisniety: bool, pin: str = "", synchronizacja: bool = False) -> None:
        if not 1 <= numer <= len(self.pola):
            return
        pole = self.pola[numer - 1]
        if pin:
            pole.pin = pin
        if pole.wcisniety == wcisniety:
            return
        pole.wcisniety = wcisniety
        opis_pinu = f" ({pole.pin})" if pole.pin != "?" else ""
        if wcisniety:
            pole.od_kiedy = time.monotonic()
            if synchronizacja and self._pierwszy_stan:
                pole.podejrzany = True
                self._log(f"Przycisk {numer}{opis_pinu} jest wciśnięty od startu - "
                          "jeśli go nie trzymasz, sprawdź czy pin nie zwiera do GND.")
            else:
                pole.licznik += 1
                pole.sprawdzony = True
                self._log(f"Przycisk {numer}{opis_pinu} wciśnięty")
        else:
            if pole.podejrzany:
                pole.podejrzany = False
                self._log(f"Przycisk {numer}{opis_pinu} puszczony - wygląda dobrze.")
            else:
                czas = time.monotonic() - pole.od_kiedy
                self._log(f"Przycisk {numer}{opis_pinu} puszczony po {czas:.2f} s")
        self._rysuj(numer - 1)
        self._postep()

    def stan(self, bity: str) -> None:
        for numer, ch in enumerate(bity, start=1):
            if ch in "01":
                self.zmiana(numer, ch == "1", synchronizacja=True)
        self._pierwszy_stan = False

    def reset(self) -> None:
        for i, pole in enumerate(self.pola):
            pole.licznik = 0
            pole.sprawdzony = False
            self._rysuj(i)
        self._postep()
        self.dziennik.delete(0, "end")


# ============================ zakladka: LED ================================

def _odwroc(slownik: dict) -> dict:
    return {v: k for k, v in slownik.items()}


class ZakladkaLedy(ttk.Frame):
    STANY_SYMULACJI = [
        ("jazda", "Jazda (obroty)"),
        ("pit", "Pit limiter"),
        ("zolta", "Flaga żółta"),
        ("niebieska", "Flaga niebieska"),
        ("brak_gry", "Gra wyłączona"),
    ]

    def __init__(self, master, aplikacja: "Aplikacja") -> None:
        super().__init__(master, padding=10)
        self.app = aplikacja
        self.sciezka = fx.PLIK_USTAWIEN
        self.zmieniono = False
        self._laduje = False
        self._powiazania: list[tuple[tk.Variable, tuple, object]] = []
        self._zaznaczone: set[int] = set()
        self._wzor_kolorow: list[str] = []
        self._ostatnia_linia = ""
        self._ostatnie_wyslanie = 0.0
        self._wyslano_cos = False
        self._t0 = time.monotonic()

        try:
            self.u = fx.wczytaj(self.sciezka)
            blad = None
        except ValueError as exc:
            self.u = fx.domyslne_ustawienia()
            blad = str(exc)

        self.columnconfigure(0, weight=3, uniform="kol")
        self.columnconfigure(1, weight=2, uniform="kol")
        self.rowconfigure(0, weight=1)

        lewa = Przewijany(self)
        lewa.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        prawa = ttk.Frame(self)
        prawa.grid(row=0, column=1, sticky="nsew")

        self._buduj_ustawienia(lewa.wnetrze)
        self._buduj_podglad(prawa)
        self._buduj_przyciski()
        self._wczytaj_do_pol()
        if blad:
            self.after(300, lambda: messagebox.showwarning(
                "Diody LED", f"{blad}\n\nWczytano ustawienia domyślne.", parent=self))
        self._tik()

    # ------------------------------------------------------------ powiazania
    def _wiaz(self, zmienna: tk.Variable, sciezka: tuple, konwersja=None, po=None) -> tk.Variable:
        """Laczy zmienna Tk z polem w self.u (sciezka = klucze w slowniku)."""
        self._powiazania.append((zmienna, sciezka, konwersja))

        def zmiana(*_):
            if self._laduje:
                return
            try:
                wartosc = zmienna.get()
                if isinstance(konwersja, dict):
                    wartosc = konwersja[wartosc]
                elif konwersja:
                    wartosc = konwersja(wartosc)
            except (tk.TclError, ValueError, KeyError):
                return
            d = self.u
            for klucz in sciezka[:-1]:
                d = d[klucz]
            if d.get(sciezka[-1]) == wartosc:
                return
            d[sciezka[-1]] = wartosc
            if po:
                po()
            self._zmiana()

        zmienna.trace_add("write", zmiana)
        return zmienna

    def _pobierz(self, sciezka: tuple):
        d = self.u
        for klucz in sciezka:
            d = d[klucz]
        return d

    def _wczytaj_do_pol(self) -> None:
        """Przepisuje self.u do wszystkich pol formularza."""
        self._odswiez_pola()
        self._wzor_kolorow = list(self.u["kolory"])
        self._zaznaczone.clear()
        self._rysuj_edytor()

    def _odswiez_pola(self) -> None:
        self._laduje = True
        try:
            for zmienna, sciezka, konwersja in self._powiazania:
                wartosc = self._pobierz(sciezka)
                if isinstance(konwersja, dict):            # mapa: wyswietlana nazwa -> klucz
                    wartosc = _odwroc(konwersja)[wartosc]
                elif isinstance(wartosc, float) and wartosc.is_integer():
                    wartosc = int(wartosc)
                zmienna.set(wartosc)
            for sciezka, probka in self._probki:
                probka.ustaw(self._pobierz(sciezka))
        finally:
            self._laduje = False

    def _zmiana(self) -> None:
        if self._laduje:
            return
        self.zmieniono = True
        self._odswiez_tytul()

    def _odswiez_tytul(self) -> None:
        gw = " • niezapisane zmiany" if self.zmieniono else ""
        self.etykieta_pliku.configure(text=f"Plik: {self.sciezka}{gw}")
        self.app.odswiez_tytul()

    # ---------------------------------------------------------------- budowa
    def _sekcja(self, rodzic, tytul: str) -> ttk.LabelFrame:
        ramka = ttk.LabelFrame(rodzic, text=tytul, padding=10)
        ramka.pack(fill="x", pady=(0, 10), padx=(0, 4))
        return ramka

    def _spin(self, rodzic, od, do, krok=1.0, szer=6) -> ttk.Spinbox:
        sp = ttk.Spinbox(rodzic, from_=od, to=do, increment=krok, width=szer)
        # po wyjsciu z pola pokaz wartosc faktycznie przyjeta (np. 75 -> 60)
        sp.bind("<FocusOut>", lambda e: self._odswiez_pola())
        return sp

    def _buduj_ustawienia(self, r) -> None:
        self._probki: list[tuple[tuple, Probka]] = []
        mapa_kier = {v: k for k, v in fx.KIERUNKI.items()}

        # --- pasek ---
        s = self._sekcja(r, "Pasek LED")
        ttk.Label(s, text="Liczba diod:").grid(row=0, column=0, sticky="w")
        self.v_liczba = self._wiaz(tk.IntVar(), ("liczba_diod",),
                                   lambda v: max(1, min(fx.MAX_DIOD, int(v))), po=self._po_liczbie)
        sp = self._spin(s, 1, fx.MAX_DIOD, 1)
        sp.configure(textvariable=self.v_liczba)
        sp.grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(s, text="Jasność:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.v_jasnosc = self._wiaz(tk.IntVar(), ("jasnosc",), int)
        ttk.Scale(s, from_=0, to=100, orient="horizontal", length=220,
                  command=lambda v: self.v_jasnosc.set(round(float(v))),
                  variable=self.v_jasnosc).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(s, textvariable=self.v_jasnosc, width=4).grid(row=1, column=2, sticky="w",
                                                                pady=(8, 0))
        ttk.Label(s, text="%").grid(row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Label(s, text="Kierunek zapalania:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.v_kierunek = self._wiaz(tk.StringVar(), ("kierunek",), mapa_kier)
        ttk.Combobox(s, textvariable=self.v_kierunek, values=list(mapa_kier), state="readonly",
                     width=24).grid(row=2, column=1, columnspan=3, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(s, text="Przy zasilaniu z USB trzymaj jasność ≤ 40% "
                  "(każda dioda na biało przy 100% pobiera ok. 60 mA).",
                  foreground="#666", wraplength=520).grid(row=3, column=0, columnspan=4,
                                                          sticky="w", pady=(8, 0))

        # --- kolory ---
        s = self._sekcja(r, "Kolory diod")
        ttk.Label(s, text="Kliknij diody, aby je zaznaczyć, potem „Zmień kolor zaznaczonych”. "
                  "Dwuklik zmienia kolor jednej diody.",
                  foreground="#666", wraplength=520).pack(anchor="w")
        self.edytor = tk.Canvas(s, height=70, bg=KOLOR_TLO_PASKA, highlightthickness=0)
        self.edytor.pack(fill="x", pady=6)
        self.edytor.bind("<Configure>", lambda e: self._rysuj_edytor())
        self.edytor.bind("<Button-1>", self._klik_edytor)
        self.edytor.bind("<Double-Button-1>", self._dwuklik_edytor)

        w = ttk.Frame(s)
        w.pack(fill="x")
        ttk.Button(w, text="Zmień kolor zaznaczonych…", command=self._kolor_zaznaczonych).pack(
            side="left")
        ttk.Button(w, text="Zaznacz wszystkie", command=self._zaznacz_wszystkie).pack(
            side="left", padx=6)
        ttk.Button(w, text="Odznacz", command=self._odznacz).pack(side="left")

        w = ttk.Frame(s)
        w.pack(fill="x", pady=(10, 0))
        ttk.Label(w, text="Gotowy zestaw:").pack(side="left")
        mapa_presetow = {v: k for k, v in fx.PRESETY.items()}
        self.v_preset = tk.StringVar(value=fx.PRESETY["klasyczny"])
        ttk.Combobox(w, textvariable=self.v_preset, values=list(mapa_presetow), state="readonly",
                     width=36).pack(side="left", padx=6)
        ttk.Button(w, text="Zastosuj",
                   command=lambda: self._ustaw_kolory(fx.kolory_presetu(
                       mapa_presetow[self.v_preset.get()], self.u["liczba_diod"],
                       self.u["kierunek"]))).pack(side="left")

        w = ttk.Frame(s)
        w.pack(fill="x", pady=(8, 0))
        ttk.Label(w, text="Własny gradient:").pack(side="left")
        self.gradient = []
        for kolor, opis in (("#00FF00", "pierwsza dioda"), ("#FFDC00", "środek"),
                            ("#FF0000", "ostatnia dioda")):
            p = Probka(w, kolor, lambda _k: None, f"Gradient: {opis}")
            p.pack(side="left", padx=3)
            self.gradient.append(p)
        ttk.Button(w, text="Zastosuj gradient", command=self._zastosuj_gradient).pack(
            side="left", padx=6)

        # --- progi ---
        s = self._sekcja(r, "Kiedy zapalają się diody (obroty silnika)")
        ttk.Label(s, text="Pierwsza dioda przy:").grid(row=0, column=0, sticky="w")
        self.v_start = self._wiaz(tk.StringVar(), ("obroty", "start"), self._procent)
        sp = self._spin(s, 0, 100, 1)
        sp.configure(textvariable=self.v_start)
        sp.grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(s, text="% maks. obrotów").grid(row=0, column=2, sticky="w")

        ttk.Label(s, text="Wszystkie diody przy:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.v_pelne = self._wiaz(tk.StringVar(), ("obroty", "pelne"), self._procent)
        sp = self._spin(s, 0, 100, 1)
        sp.configure(textvariable=self.v_pelne)
        sp.grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))
        ttk.Label(s, text="% maks. obrotów").grid(row=1, column=2, sticky="w", pady=(6, 0))

        ttk.Label(s, text="Miganie „zmień bieg” od:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.v_prog = self._wiaz(tk.StringVar(), ("stany", "zmiana_biegu", "prog"), self._procent)
        sp = self._spin(s, 0, 100, 1)
        sp.configure(textvariable=self.v_prog)
        sp.grid(row=2, column=1, padx=6, sticky="w", pady=(6, 0))
        ttk.Label(s, text="% maks. obrotów").grid(row=2, column=2, sticky="w", pady=(6, 0))

        # --- stany ---
        s = self._sekcja(r, "Stany specjalne")
        for kol, tekst in enumerate(("Stan", "Włączony", "Kolor", "Miganie [Hz]", "Opcje")):
            ttk.Label(s, text=tekst, foreground="#666").grid(row=0, column=kol, sticky="w",
                                                             padx=(0, 10), pady=(0, 4))

        def wiersz(rzad: int, nazwa: str, opis: str) -> ttk.Frame:
            ttk.Label(s, text=opis).grid(row=rzad, column=0, sticky="w", pady=3, padx=(0, 10))
            v = self._wiaz(tk.BooleanVar(), ("stany", nazwa, "wlaczony"), bool)
            ttk.Checkbutton(s, variable=v).grid(row=rzad, column=1, sticky="w")
            self._probka(s, ("stany", nazwa, "kolor"), opis).grid(row=rzad, column=2, sticky="w")
            v = self._wiaz(tk.StringVar(), ("stany", nazwa, "miganie_hz"), self._hz)
            sp = self._spin(s, 0, 20, 0.5, 5)
            sp.configure(textvariable=v)
            sp.grid(row=rzad, column=3, sticky="w")
            opcje = ttk.Frame(s)
            opcje.grid(row=rzad, column=4, sticky="w")
            return opcje

        wiersz(1, "zmiana_biegu", "Zmiana biegu (limiter)")
        opcje = wiersz(2, "pit_limiter", "Pit limiter")
        mapa_pit = {v: k for k, v in fx.WZORY_PIT.items()}
        v = self._wiaz(tk.StringVar(), ("stany", "pit_limiter", "wzor"), mapa_pit)
        ttk.Combobox(opcje, textvariable=v, values=list(mapa_pit), state="readonly",
                     width=28).pack(side="left")
        wiersz(3, "flaga_zolta", "Flaga żółta")
        wiersz(4, "flaga_niebieska", "Flaga niebieska")

        f = ttk.Frame(s)
        f.grid(row=5, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Label(f, text="Flagi pokazuj na").pack(side="left")
        v = self._wiaz(tk.IntVar(), ("stany", "flagi_diody_skrajne"),
                       lambda x: max(0, min(fx.MAX_DIOD // 2, int(x))))
        sp = self._spin(f, 0, fx.MAX_DIOD // 2, 1, 4)
        sp.configure(textvariable=v)
        sp.pack(side="left", padx=6)
        ttk.Label(f, text="skrajnych diodach z każdej strony (0 = cały pasek)").pack(side="left")

        ttk.Separator(s).grid(row=6, column=0, columnspan=5, sticky="ew", pady=8)
        ttk.Label(s, text="Gra wyłączona").grid(row=7, column=0, sticky="w")
        self._probka(s, ("stany", "brak_gry", "kolor"), "Gra wyłączona").grid(
            row=7, column=2, sticky="w")
        mapa_bezcz = {v: k for k, v in fx.TRYBY_BEZCZYNNOSCI.items()}
        v = self._wiaz(tk.StringVar(), ("stany", "brak_gry", "tryb"), mapa_bezcz)
        ttk.Combobox(s, textvariable=v, values=list(mapa_bezcz), state="readonly",
                     width=28).grid(row=7, column=3, columnspan=2, sticky="w")

        ttk.Label(s, text="Ważność: gra wyłączona → pit limiter → zmiana biegu → obroty. "
                  "Flagi świecą na wierzchu (na skrajnych diodach). Miganie 0 Hz = świeci ciągle.",
                  foreground="#666", wraplength=520).grid(row=8, column=0, columnspan=5,
                                                          sticky="w", pady=(10, 0))

    @staticmethod
    def _procent(v) -> float:
        x = float(v)
        if not 0 <= x <= 100:
            raise ValueError
        return x

    @staticmethod
    def _hz(v) -> float:
        x = float(v)
        if not 0 <= x <= 20:
            raise ValueError
        return x

    def _probka(self, rodzic, sciezka: tuple, opis: str) -> Probka:
        def zmiana(kolor: str) -> None:
            d = self.u
            for klucz in sciezka[:-1]:
                d = d[klucz]
            d[sciezka[-1]] = kolor
            self._zmiana()
        p = Probka(rodzic, self._pobierz(sciezka), zmiana, f"Kolor: {opis}")
        self._probki.append((sciezka, p))
        return p

    def _buduj_podglad(self, r) -> None:
        s = ttk.LabelFrame(r, text="Podgląd na żywo", padding=10)
        s.pack(fill="x")
        self.podglad = tk.Canvas(s, height=90, bg=KOLOR_TLO_PASKA, highlightthickness=0)
        self.podglad.pack(fill="x")
        self.opis_podgladu = ttk.Label(s, text="")
        self.opis_podgladu.pack(anchor="w", pady=(6, 0))

        s = ttk.LabelFrame(r, text="Symulacja (sprawdź efekty bez uruchamiania gry)", padding=10)
        s.pack(fill="x", pady=10)
        self.v_stan = tk.StringVar(value="jazda")
        for klucz, opis in self.STANY_SYMULACJI:
            ttk.Radiobutton(s, text=opis, value=klucz, variable=self.v_stan).pack(anchor="w")

        w = ttk.Frame(s)
        w.pack(fill="x", pady=(10, 0))
        ttk.Label(w, text="Obroty:").pack(side="left")
        self.v_obroty = tk.DoubleVar(value=80)
        ttk.Scale(w, from_=0, to=100, orient="horizontal", variable=self.v_obroty,
                  command=lambda _v: self.v_auto.set(False)).pack(side="left", fill="x",
                                                                   expand=True, padx=6)
        self.etykieta_obrotow = ttk.Label(w, text="", width=6)
        self.etykieta_obrotow.pack(side="left")

        self.v_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(s, text="Automatyczna jazda (obroty rosną same)",
                        variable=self.v_auto).pack(anchor="w", pady=(6, 0))

        s = ttk.LabelFrame(r, text="Pasek w kierownicy", padding=10)
        s.pack(fill="x")
        self.v_wysylaj = tk.BooleanVar(value=True)
        ttk.Checkbutton(s, text="Pokazuj podgląd na prawdziwym pasku LED",
                        variable=self.v_wysylaj).pack(anchor="w")
        self.status_paska = ttk.Label(s, text="", foreground="#666", wraplength=380)
        self.status_paska.pack(anchor="w", pady=(4, 0))

    def _buduj_przyciski(self) -> None:
        dol = ttk.Frame(self)
        dol.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(dol, text="Zapisz", command=self.zapisz).pack(side="left")
        ttk.Button(dol, text="Zapisz jako…", command=self.zapisz_jako).pack(side="left", padx=6)
        ttk.Button(dol, text="Wczytaj z pliku…", command=self.wczytaj_plik).pack(side="left")
        ttk.Button(dol, text="Przywróć domyślne", command=self.domyslne).pack(side="left", padx=6)
        self.etykieta_pliku = ttk.Label(dol, text="", foreground="#666")
        self.etykieta_pliku.pack(side="right")
        self._odswiez_tytul()

    # ---------------------------------------------------------- edytor kolorow
    def _geometria(self, canvas: tk.Canvas, n: int):
        """Pozycje srodkow diod na plotnie: lista (x, y, r)."""
        szer = max(canvas.winfo_width(), 200)
        wys = int(canvas.cget("height"))
        rzedy = 1 if n <= 24 else 2
        na_rzad = math.ceil(n / rzedy)
        krok = (szer - 20) / na_rzad
        r = max(4, min(18, krok * 0.38, wys / (2.6 * rzedy)))
        wynik = []
        for i in range(n):
            rz, kol = divmod(i, na_rzad)
            x = 10 + krok * (kol + 0.5)
            y = wys * (rz + 0.5) / rzedy
            wynik.append((x, y, r))
        return wynik

    def _rysuj_edytor(self) -> None:
        c = self.edytor
        c.delete("all")
        n = self.u["liczba_diod"]
        for i, (x, y, r) in enumerate(self._geometria(c, n)):
            kolor = self.u["kolory"][i]
            if i in self._zaznaczone:
                c.create_oval(x - r - 4, y - r - 4, x + r + 4, y + r + 4, outline="white", width=2)
            c.create_oval(x - r, y - r, x + r, y + r, fill=kolor, outline="#000")
            if r >= 9:
                c.create_text(x, y + r + 2, text=str(i + 1), fill="#9aa0a8", anchor="n",
                              font=("TkDefaultFont", 7))

    def _ktora_dioda(self, e) -> int | None:
        for i, (x, y, r) in enumerate(self._geometria(self.edytor, self.u["liczba_diod"])):
            if (e.x - x) ** 2 + (e.y - y) ** 2 <= (r + 4) ** 2:
                return i
        return None

    def _klik_edytor(self, e) -> None:
        i = self._ktora_dioda(e)
        if i is None:
            return
        self._zaznaczone ^= {i}
        self._rysuj_edytor()

    def _dwuklik_edytor(self, e) -> None:
        i = self._ktora_dioda(e)
        if i is None:
            return
        nowy = wybor_kolor(self, self.u["kolory"][i], f"Kolor diody {i + 1}")
        if nowy:
            self.u["kolory"][i] = nowy
            self._wzor_kolorow = list(self.u["kolory"])
            self._zaznaczone.discard(i)
            self._zmiana()
        self._rysuj_edytor()

    def _kolor_zaznaczonych(self) -> None:
        if not self._zaznaczone:
            messagebox.showinfo("Kolory diod", "Najpierw kliknij diody, które chcesz zmienić.",
                                parent=self)
            return
        pierwsza = min(self._zaznaczone)
        nowy = wybor_kolor(self, self.u["kolory"][pierwsza],
                           f"Kolor dla {len(self._zaznaczone)} diod")
        if nowy:
            for i in self._zaznaczone:
                self.u["kolory"][i] = nowy
            self._wzor_kolorow = list(self.u["kolory"])
            self._zaznaczone.clear()
            self._zmiana()
            self._rysuj_edytor()

    def _zaznacz_wszystkie(self) -> None:
        self._zaznaczone = set(range(self.u["liczba_diod"]))
        self._rysuj_edytor()

    def _odznacz(self) -> None:
        self._zaznaczone.clear()
        self._rysuj_edytor()

    def _ustaw_kolory(self, kolory: list) -> None:
        self.u["kolory"] = [fx.kolor_na_hex(k) for k in kolory]
        self._wzor_kolorow = list(self.u["kolory"])
        self._zaznaczone.clear()
        self._zmiana()
        self._rysuj_edytor()

    def _zastosuj_gradient(self) -> None:
        punkty = [fx.hex_na_kolor(p.kolor) for p in self.gradient]
        self._ustaw_kolory(fx.kolory_gradient(self.u["liczba_diod"], self.u["kierunek"], punkty))

    def _po_liczbie(self) -> None:
        # Rozciaga/sciska ostatnio ustawiony wzor kolorow na nowa liczbe diod,
        # zeby strefy (zielona/zolta/czerwona) zostaly w tych samych proporcjach.
        wzor = self._wzor_kolorow or self.u["kolory"]
        n = self.u["liczba_diod"]
        if n == 1 or len(wzor) == 1:
            self.u["kolory"] = [wzor[0]] * n
        else:
            self.u["kolory"] = [wzor[round(i * (len(wzor) - 1) / (n - 1))] for i in range(n)]
        self.u = fx.popraw_ustawienia(self.u)
        self._zaznaczone = {i for i in self._zaznaczone if i < self.u["liczba_diod"]}
        self._rysuj_edytor()

    # --------------------------------------------------------------- pliki
    def zapisz(self) -> bool:
        try:
            self.u = fx.popraw_ustawienia(self.u)
            fx.zapisz(self.u, self.sciezka)
        except OSError as exc:
            messagebox.showerror("Zapis", f"Nie udało się zapisać pliku:\n{exc}", parent=self)
            return False
        self.zmieniono = False
        self._wczytaj_do_pol()
        self._odswiez_tytul()
        return True

    def zapisz_jako(self) -> None:
        sciezka = filedialog.asksaveasfilename(
            parent=self, title="Zapisz ustawienia LED", defaultextension=".json",
            initialdir=str(Path(self.sciezka).parent), initialfile=Path(self.sciezka).name,
            filetypes=[("Ustawienia LED", "*.json"), ("Wszystkie pliki", "*.*")])
        if sciezka:
            self.sciezka = Path(sciezka)
            self.zapisz()

    def wczytaj_plik(self) -> None:
        if not self.pytaj_o_zapis():
            return
        sciezka = filedialog.askopenfilename(
            parent=self, title="Wczytaj ustawienia LED", initialdir=str(Path(self.sciezka).parent),
            filetypes=[("Ustawienia LED", "*.json"), ("Wszystkie pliki", "*.*")])
        if not sciezka:
            return
        try:
            self.u = fx.wczytaj(sciezka)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Wczytywanie", str(exc), parent=self)
            return
        self.sciezka = Path(sciezka)
        self.zmieniono = False
        self._wczytaj_do_pol()
        self._odswiez_tytul()

    def domyslne(self) -> None:
        if not messagebox.askyesno("Przywróć domyślne",
                                   "Przywrócić domyślne ustawienia diod? "
                                   "(Plik zmieni się dopiero po kliknięciu „Zapisz”.)", parent=self):
            return
        self.u = fx.domyslne_ustawienia()
        self._wczytaj_do_pol()
        self._zmiana()

    def pytaj_o_zapis(self) -> bool:
        """False = uzytkownik anulowal."""
        if not self.zmieniono:
            return True
        odp = messagebox.askyesnocancel("Niezapisane zmiany",
                                        "Masz niezapisane zmiany w ustawieniach diod. Zapisać?",
                                        parent=self)
        if odp is None:
            return False
        if odp:
            return self.zapisz()
        return True

    # ------------------------------------------------------------- animacja
    def _telemetria(self, t: float) -> fx.Telemetria:
        if self.v_auto.get():
            cykl = t % 4.5
            if cykl < 3.5:
                obroty = 0.45 + 0.57 * (cykl / 3.5) ** 1.3
            else:
                obroty = 1.0
            obroty = min(obroty, 1.0)
            self.v_obroty.set(round(obroty * 100, 1))
        obroty = self.v_obroty.get() / 100.0
        stan = self.v_stan.get()
        return fx.Telemetria(
            obroty=obroty,
            gra_aktywna=stan != "brak_gry",
            pit_limiter=stan == "pit",
            flaga={"zolta": "zolta", "niebieska": "niebieska"}.get(stan),
        )

    def _tik(self) -> None:
        try:
            t = time.monotonic() - self._t0
            u = fx.popraw_ustawienia(self.u)
            tel = self._telemetria(t)
            kolory = fx.klatka(u, tel, t)
            self._rysuj_podglad(kolory)
            self.etykieta_obrotow.configure(text=f"{tel.obroty * 100:3.0f} %")
            self.opis_podgladu.configure(text=f"{len(kolory)} diod · jasność na pasku "
                                              f"{u['jasnosc']}% · obroty {tel.obroty * 100:.0f}%")
            self._wyslij(fx.z_jasnoscia(kolory, u["jasnosc"]))
        finally:
            self.after(int(1000 / FPS), self._tik)

    def _rysuj_podglad(self, kolory: list) -> None:
        c = self.podglad
        c.delete("all")
        for (x, y, r), kolor in zip(self._geometria(c, len(kolory)), kolory):
            if kolor == fx.CZARNY:
                c.create_oval(x - r, y - r, x + r, y + r, fill=KOLOR_DIODA_OFF, outline="#000")
                continue
            poswiata = fx.kolor_na_hex(fx.mieszaj(fx.hex_na_kolor(KOLOR_TLO_PASKA), kolor, 0.35))
            c.create_oval(x - r * 1.45, y - r * 1.45, x + r * 1.45, y + r * 1.45,
                          fill=poswiata, outline="")
            c.create_oval(x - r, y - r, x + r, y + r, fill=fx.kolor_na_hex(kolor), outline="#000")

    def _wyslij(self, kolory: list) -> None:
        pol = self.app.polaczenie
        info = pol.info if pol.polaczony else None
        if not self.v_wysylaj.get() or info is None or info.max_leds == 0:
            if self._wyslano_cos and pol.polaczony:
                pol.wyslij("LEDS")
            self._wyslano_cos = False
            self._ostatnia_linia = ""
            if not pol.polaczony:
                tekst = "Kierownica niepołączona - podgląd tylko na ekranie."
            elif info is None or info.max_leds == 0:
                tekst = ("Firmware w kierownicy nie obsługuje paska LED. Wgraj nową wersję "
                         "(kierownica_gt.ino 1.1 lub nowszą) z LED_ENABLED = 1.")
            else:
                tekst = "Wyłączone - pasek w kierownicy jest zgaszony."
            self.status_paska.configure(text=tekst)
            return

        kolory = kolory[:info.max_leds]
        linia = fx.komenda_leds(kolory)
        teraz = time.monotonic()
        # ~70% przepustowosci 115200 bodow: przy 60 diodach max ok. 20 klatek/s
        min_odstep = max(1.0 / FPS, len(linia) / 8000.0)
        if teraz - self._ostatnie_wyslanie < min_odstep:
            return
        if linia == self._ostatnia_linia and teraz - self._ostatnie_wyslanie < 1.0:
            return
        if pol.wyslij(linia):
            self._ostatnia_linia = linia
            self._ostatnie_wyslanie = teraz
            self._wyslano_cos = True
            self.status_paska.configure(
                text=f"Wysyłam podgląd na pasek ({len(kolory)} diod, max {info.max_leds}).")

    def rozlaczono(self) -> None:
        self._wyslano_cos = False
        self._ostatnia_linia = ""


# ============================== aplikacja ==================================

class Aplikacja(tk.Tk):
    def __init__(self, port: str | None) -> None:
        super().__init__()
        self.title("Kierownica GT – konfigurator")
        self.geometry("1180x780")
        self.minsize(980, 640)
        self.q: queue.Queue = queue.Queue()
        self.polaczenie = Polaczenie(self.q)
        self._gen = 0
        self._chce_polaczenia = True
        self._ponow_id = None

        styl = ttk.Style(self)
        if "vista" in styl.theme_names():
            styl.theme_use("vista")
        elif "clam" in styl.theme_names():
            styl.theme_use("clam")

        self._buduj_gore(port)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.przyciski = ZakladkaPrzyciski(nb)
        self.ledy = ZakladkaLedy(nb, self)
        nb.add(self.przyciski, text="  Test przycisków  ")
        nb.add(self.ledy, text="  Diody LED  ")

        self.bind_all("<Control-s>", lambda e: self.ledy.zapisz())
        self.protocol("WM_DELETE_WINDOW", self.zamknij)
        self.after(50, self._kolejka)
        self.after(200, self.polacz)

    # ---------------------------------------------------------- gorny pasek
    def _buduj_gore(self, port: str | None) -> None:
        g = ttk.Frame(self, padding=(10, 10, 10, 6))
        g.pack(fill="x")
        self.kropka = tk.Canvas(g, width=14, height=14, highlightthickness=0)
        self.kropka.pack(side="left")
        self.status = ttk.Label(g, text="")
        self.status.pack(side="left", padx=(6, 0))

        self.przycisk_polacz = ttk.Button(g, text="Rozłącz", command=self._przelacz, width=10)
        self.przycisk_polacz.pack(side="right")
        ttk.Button(g, text="⟳", width=3, command=self._odswiez_porty).pack(side="right", padx=4)
        self.v_port = tk.StringVar(value=port or AUTO)
        self.lista_portow = ttk.Combobox(g, textvariable=self.v_port, width=16, state="readonly")
        self.lista_portow.pack(side="right")
        self.lista_portow.bind("<<ComboboxSelected>>", lambda e: self.polacz())
        ttk.Label(g, text="Port:").pack(side="right", padx=(0, 4))
        self._odswiez_porty()
        self._status("Szukam kierownicy…", "#e0a000")

    def _odswiez_porty(self) -> None:
        porty = [p.device for p in list_candidate_ports()]
        obecny = self.v_port.get()
        if obecny not in (AUTO, *porty):
            porty.append(obecny)
        self.lista_portow.configure(values=[AUTO, *porty])

    def _status(self, tekst: str, kolor: str) -> None:
        self.status.configure(text=tekst)
        self.kropka.delete("all")
        self.kropka.create_oval(2, 2, 12, 12, fill=kolor, outline="")

    def odswiez_tytul(self) -> None:
        gw = " *" if getattr(self, "ledy", None) and self.ledy.zmieniono else ""
        self.title(f"Kierownica GT – konfigurator{gw}")

    # -------------------------------------------------------------- laczenie
    def polacz(self) -> None:
        if self._ponow_id:
            self.after_cancel(self._ponow_id)
            self._ponow_id = None
        self._chce_polaczenia = True
        self.przycisk_polacz.configure(text="Rozłącz")
        self._rozlaczono_ui()
        port = self.v_port.get()
        self._status("Szukam kierownicy…" if port == AUTO else f"Łączę z {port}…", "#e0a000")
        self._gen = self.polaczenie.polacz(None if port == AUTO else port)

    def _przelacz(self) -> None:
        if self._chce_polaczenia:
            self._chce_polaczenia = False
            if self._ponow_id:
                self.after_cancel(self._ponow_id)
                self._ponow_id = None
            self._gen += 1   # ignoruj wiadomosci ze starego polaczenia
            self.polaczenie.rozlacz()
            self._rozlaczono_ui()
            self._status("Rozłączono.", "#888888")
            self.przycisk_polacz.configure(text="Połącz")
        else:
            self.polacz()

    def _ponow(self) -> None:
        if self._chce_polaczenia:
            self._ponow_id = self.after(int(RETRY_S * 1000), self.polacz)

    def _rozlaczono_ui(self) -> None:
        self.przyciski.rozlaczono()
        self.ledy.rozlaczono()

    def _kolejka(self) -> None:
        try:
            while True:
                wiad = self.q.get_nowait()
                if wiad[1] != self._gen:
                    continue
                self._obsluz(wiad)
        except queue.Empty:
            pass
        self.after(20, self._kolejka)

    def _obsluz(self, wiad: tuple) -> None:
        rodzaj = wiad[0]
        if rodzaj == "polaczono":
            _, _, port, info = wiad
            led = f"pasek LED: do {info.max_leds} diod" if info.max_leds else "bez obsługi LED"
            self._status(f"Połączono: {port} · firmware {info.version} · "
                         f"{info.n_buttons} przycisków · {led}", "#2ecc71")
            self.przyciski.polaczono(info)
            self.polaczenie.wyslij("INFO")
            self.polaczenie.wyslij("STATE?")
        elif rodzaj == "brak":
            _, _, zajete, nazwy = wiad
            if zajete:
                tekst = (f"Port {', '.join(zajete)} jest zajęty - zamknij okno Kierownica GT "
                         "(Kierownica_GT.bat) albo Serial Monitor. Próbuję dalej…")
            elif not nazwy:
                tekst = "Brak portów COM - podłącz kierownicę kablem USB. Szukam dalej…"
            else:
                tekst = "Nie znaleziono kierownicy. Szukam dalej…"
            self._status(tekst, "#e04040")
            self._ponow()
        elif rodzaj == "utracono":
            self._status(f"Utracono połączenie ({wiad[2]}). Szukam ponownie…", "#e04040")
            self._rozlaczono_ui()
            self._ponow()
        elif rodzaj == "linia":
            self._linia(wiad[2])

    def _linia(self, tekst: str) -> None:
        cz = tekst.split()
        if not cz:
            return
        if cz[0] == "BTN" and len(cz) >= 3 and cz[1].isdigit():
            self.przyciski.zmiana(int(cz[1]), cz[2].upper() == "ON", cz[3] if len(cz) >= 4 else "")
        elif cz[0] == "STATE" and len(cz) >= 2:
            self.przyciski.stan(cz[1])
        elif cz[0] == "INFO" and len(cz) >= 5 and cz[1] == "BTN" and cz[2].isdigit() \
                and cz[3] == "PIN":
            self.przyciski.ustaw_pin(int(cz[2]), cz[4])

    def zamknij(self) -> None:
        if not self.ledy.pytaj_o_zapis():
            return
        self._gen += 1
        self.polaczenie.rozlacz()
        self.destroy()


def main() -> None:
    ap = argparse.ArgumentParser(description="Kierownica GT - konfigurator")
    ap.add_argument("--port", help="konkretny port, np. COM5 (domyślnie: automatycznie)")
    args = ap.parse_args()

    if sys.platform == "win32":
        try:  # ostre napisy na ekranach z powiekszeniem (125%, 150%)
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    Aplikacja(args.port).mainloop()


if __name__ == "__main__":
    main()
