# -*- coding: utf-8 -*-
"""
GT Wheel - LED strip effects (revs, shift light, pit limiter, flags).

This module doesn't depend on any windows or the serial port. It only computes
which colour each LED should show, based on:
  * the settings from leds.json (colours, thresholds, effects),
  * telemetry (revs, pit limiter, flag, whether a game is running),
  * time (for blinking and animations).

Used by the configurator (preview) and by the program while you play.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path

Kolor = tuple[int, int, int]

PLIK_USTAWIEN = Path(__file__).with_name("leds.json")
MAX_DIOD = 60
CZARNY: Kolor = (0, 0, 0)

KIERUNKI = {
    "lewo_prawo": "od lewej do prawej",
    "prawo_lewo": "od prawej do lewej",
    "od_srodka": "od środka na boki",
    "do_srodka": "z boków do środka",
}

WZORY_PIT = {
    "caly": "cały pasek miga",
    "naprzemiennie": "naprzemiennie (co druga dioda)",
    "polowki": "połówki na zmianę",
}

TRYBY_BEZCZYNNOSCI = {
    "oczekiwanie": "oczekiwanie (środkowe diody przygaszone)",
    "wylaczone": "diody zgaszone",
    "staly": "stały kolor",
    "oddech": "oddech (powolne pulsowanie)",
    "skaner": "skaner (biegające światło)",
}

USTAWIENIA_DOMYSLNE: dict = {
    "wersja": 1,
    "liczba_diod": 16,
    "animacja_startu": "fala",   # once after the wheel connects: "fala" (wave) / "tecza" (rainbow) / "wylaczona" (off)
    "jasnosc": 40,
    "kierunek": "lewo_prawo",
    "kolory": [],  # filled in from the "klasyczny" (classic) preset
    "obroty": {
        "start": 60,   # % of revs at which the first LED lights up
        "pelne": 95,   # % of revs at which all LEDs are lit
    },
    "stany": {
        "zmiana_biegu": {"wlaczony": True, "prog": 97, "kolor": "#0040FF", "miganie_hz": 8.0},
        "pit_limiter": {"wlaczony": True, "kolor": "#FF00C8", "miganie_hz": 2.0,
                        "wzor": "naprzemiennie"},
        "flaga_zolta": {"wlaczony": True, "kolor": "#FFC000", "miganie_hz": 3.0},
        "flaga_niebieska": {"wlaczony": True, "kolor": "#0060FF", "miganie_hz": 3.0},
        "flagi_diody_skrajne": 2,  # how many LEDs on each side show the flag (0 = whole strip)
        "brak_gry": {"tryb": "oczekiwanie", "kolor": "#0030FF"},
        # car alongside: the outer LEDs on its side
        "spotter": {"wlaczony": True, "kolor": "#FF7A00", "miganie_hz": 0.0, "diody": 2,
                    "zamien_strony": False},
    },
}


@dataclass
class Telemetria:
    obroty: float = 0.0            # 0.0 .. 1.0 (fraction of max revs)
    gra_aktywna: bool = True
    pit_limiter: bool = False
    flaga: str | None = None       # None, "zolta" (yellow) or "niebieska" (blue)
    auto_lewo: bool = False        # spotter: car alongside on the left
    auto_prawo: bool = False       # spotter: car alongside on the right


# ============================== colours =====================================

def hex_na_kolor(tekst: str) -> Kolor:
    t = str(tekst).strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError(f"zly kolor: {tekst!r}")
    return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)


def kolor_na_hex(kolor: Kolor) -> str:
    return "#{:02X}{:02X}{:02X}".format(*kolor)


def mieszaj(a: Kolor, b: Kolor, t: float) -> Kolor:
    t = min(1.0, max(0.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def przyciemnij(kolor: Kolor, wspolczynnik: float) -> Kolor:
    w = min(1.0, max(0.0, wspolczynnik))
    return tuple(round(c * w) for c in kolor)  # type: ignore[return-value]


# ============================= lighting order ==============================

def kroki_diod(n: int, kierunek: str) -> list[int]:
    """The step at which each LED lights up (0 = first)."""
    if kierunek == "prawo_lewo":
        return [n - 1 - i for i in range(n)]
    if kierunek in ("od_srodka", "do_srodka"):
        odl = [abs(2 * i - (n - 1)) // 2 for i in range(n)]
        if kierunek == "od_srodka":
            return odl
        m = max(odl)
        return [m - d for d in odl]
    return list(range(n))


def liczba_krokow(n: int, kierunek: str) -> int:
    return max(kroki_diod(n, kierunek)) + 1 if n > 0 else 0


# ============================== presets =====================================

PRESETY = {
    "klasyczny": "klasyczny: zielony / żółty / czerwony",
    "f1": "F1: zielony / czerwony / fioletowy",
    "gradient": "gradient: płynnie zielony → czerwony",
    "jeden_kolor": "jeden kolor: wszystkie białe",
}


def kolory_gradient(n: int, kierunek: str, punkty: list[Kolor]) -> list[Kolor]:
    """Colours in lighting order: first LED = punkty[0], last = punkty[-1]."""
    kroki = kroki_diod(n, kierunek)
    ile = max(kroki) if kroki else 0
    wynik = []
    for k in kroki:
        t = k / ile if ile else 0.0
        poz = t * (len(punkty) - 1)
        i = min(int(poz), len(punkty) - 2) if len(punkty) > 1 else 0
        wynik.append(mieszaj(punkty[i], punkty[min(i + 1, len(punkty) - 1)], poz - i))
    return wynik


def kolory_strefy(n: int, kierunek: str, strefy: list[tuple[float, Kolor]]) -> list[Kolor]:
    """Zones in lighting order, e.g. [(0.4, green), (0.75, yellow), (1.0, red)]."""
    kroki = kroki_diod(n, kierunek)
    ile = max(kroki) + 1 if kroki else 1
    wynik = []
    for k in kroki:
        t = (k + 0.5) / ile
        for granica, kolor in strefy:
            if t <= granica:
                wynik.append(kolor)
                break
        else:
            wynik.append(strefy[-1][1])
    return wynik


def kolory_presetu(nazwa: str, n: int, kierunek: str) -> list[Kolor]:
    if nazwa == "f1":
        return kolory_strefy(n, kierunek, [(0.34, (0, 255, 0)), (0.67, (255, 0, 0)),
                                           (1.0, (160, 0, 255))])
    if nazwa == "gradient":
        return kolory_gradient(n, kierunek, [(0, 255, 0), (255, 220, 0), (255, 0, 0)])
    if nazwa == "jeden_kolor":
        return [(255, 255, 255)] * n
    return kolory_strefy(n, kierunek, [(0.45, (0, 255, 0)), (0.75, (255, 200, 0)),
                                       (1.0, (255, 0, 0))])


# ============================ loading / saving =============================

def _scal(domyslne: dict, wlasne: dict) -> dict:
    wynik = copy.deepcopy(domyslne)
    for klucz, wartosc in wlasne.items():
        if isinstance(wynik.get(klucz), dict):
            if isinstance(wartosc, dict):          # wrong type (e.g. text instead of a section) - skip
                wynik[klucz] = _scal(wynik[klucz], wartosc)
        else:
            wynik[klucz] = wartosc
    return wynik


def _wybor(wartosc, dozwolone: dict, domyslnie: str) -> str:
    return wartosc if isinstance(wartosc, str) and wartosc in dozwolone else domyslnie


def _ogranicz(x, lo, hi, domyslnie):
    if isinstance(x, bool):
        return domyslnie
    try:
        x = float(x)
    except (TypeError, ValueError):
        return domyslnie
    if math.isnan(x) or math.isinf(x):
        return domyslnie
    return min(hi, max(lo, x))


def _kolor_lub(tekst, domyslny: str) -> str:
    try:
        return kolor_na_hex(hex_na_kolor(tekst))
    except (ValueError, TypeError):
        return domyslny


def popraw_ustawienia(u: dict) -> dict:
    """Fills in missing fields and fixes bad values (e.g. after editing the file by hand)."""
    d = USTAWIENIA_DOMYSLNE
    u = _scal(d, u if isinstance(u, dict) else {})

    u["liczba_diod"] = int(_ogranicz(u["liczba_diod"], 1, MAX_DIOD, d["liczba_diod"]))
    u["jasnosc"] = int(_ogranicz(u["jasnosc"], 0, 100, d["jasnosc"]))
    u["kierunek"] = _wybor(u["kierunek"], KIERUNKI, d["kierunek"])
    u["animacja_startu"] = _wybor(u["animacja_startu"], ANIMACJE_STARTU, d["animacja_startu"])

    n = u["liczba_diod"]
    kolory = u["kolory"] if isinstance(u["kolory"], list) else []
    if not kolory:
        kolory = [kolor_na_hex(k) for k in kolory_presetu("klasyczny", n, u["kierunek"])]
    kolory = [_kolor_lub(k, "#FFFFFF") for k in kolory]
    while len(kolory) < n:
        kolory.append(kolory[-1])
    u["kolory"] = kolory[:n]

    o = u["obroty"]
    o["start"] = _ogranicz(o["start"], 0, 100, d["obroty"]["start"])
    o["pelne"] = _ogranicz(o["pelne"], 0, 100, d["obroty"]["pelne"])
    if o["pelne"] < o["start"]:
        o["pelne"] = o["start"]

    s = u["stany"]
    for nazwa in ("zmiana_biegu", "pit_limiter", "flaga_zolta", "flaga_niebieska", "spotter"):
        st, ds = s[nazwa], d["stany"][nazwa]
        st["wlaczony"] = bool(st["wlaczony"])
        st["kolor"] = _kolor_lub(st["kolor"], ds["kolor"])
        st["miganie_hz"] = _ogranicz(st["miganie_hz"], 0, 20, ds["miganie_hz"])
    s["zmiana_biegu"]["prog"] = _ogranicz(s["zmiana_biegu"]["prog"], 0, 100,
                                          d["stany"]["zmiana_biegu"]["prog"])
    s["pit_limiter"]["wzor"] = _wybor(s["pit_limiter"]["wzor"], WZORY_PIT,
                                      d["stany"]["pit_limiter"]["wzor"])
    s["flagi_diody_skrajne"] = int(_ogranicz(s["flagi_diody_skrajne"], 0, MAX_DIOD // 2,
                                             d["stany"]["flagi_diody_skrajne"]))
    s["brak_gry"]["tryb"] = _wybor(s["brak_gry"]["tryb"], TRYBY_BEZCZYNNOSCI,
                                   d["stany"]["brak_gry"]["tryb"])
    sp = s["spotter"]
    sp["diody"] = int(_ogranicz(sp["diody"], 1, MAX_DIOD // 2, d["stany"]["spotter"]["diody"]))
    sp["zamien_strony"] = bool(sp["zamien_strony"])
    s["brak_gry"]["kolor"] = _kolor_lub(s["brak_gry"]["kolor"], d["stany"]["brak_gry"]["kolor"])
    return u


def domyslne_ustawienia() -> dict:
    return popraw_ustawienia({})


def wczytaj(sciezka: Path | str = PLIK_USTAWIEN) -> dict:
    """Loads the settings. No file = defaults. Invalid JSON raises ValueError."""
    p = Path(sciezka)
    if not p.exists():
        return domyslne_ustawienia()
    try:
        dane = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Plik {p.name} jest uszkodzony: {exc}") from exc
    return popraw_ustawienia(dane)


def zapisz(u: dict, sciezka: Path | str = PLIK_USTAWIEN) -> None:
    p = Path(sciezka)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(popraw_ustawienia(u), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


# =========================== computing a frame =============================

def _miga(t: float, hz: float) -> bool:
    """True = the 'on' phase. hz <= 0 means always on."""
    if hz <= 0:
        return True
    return (t * hz) % 1.0 < 0.5


def _pasek_obrotow(u: dict, obroty: float) -> list[Kolor]:
    n = u["liczba_diod"]
    kolory = [hex_na_kolor(k) for k in u["kolory"]]
    kroki = kroki_diod(n, u["kierunek"])
    ile = max(kroki) + 1
    start = u["obroty"]["start"] / 100.0
    pelne = u["obroty"]["pelne"] / 100.0
    wynik = []
    for i, krok in enumerate(kroki):
        prog = start if ile == 1 else start + (pelne - start) * krok / (ile - 1)
        wynik.append(kolory[i] if obroty >= prog else CZARNY)
    return wynik


def _bezczynnosc(u: dict, t: float) -> list[Kolor]:
    n = u["liczba_diod"]
    st = u["stany"]["brak_gry"]
    kolor = hex_na_kolor(st["kolor"])
    tryb = st["tryb"]
    if tryb == "oczekiwanie":           # calm, no movement: 1-2 centre LEDs dimmed
        srodek = {n // 2} if n % 2 else {n // 2 - 1, n // 2}
        przygaszony = przyciemnij(kolor, 0.35)
        return [przygaszony if i in srodek else CZARNY for i in range(n)]
    if tryb == "staly":
        return [kolor] * n
    if tryb == "oddech":
        jasnosc = 0.08 + 0.92 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0))
        return [przyciemnij(kolor, jasnosc)] * n
    if tryb == "skaner":
        if n == 1:
            return [kolor]
        faza = (t / 2.0) % 2.0                       # there (0..1) and back (1..2)
        poz = (faza if faza < 1 else 2 - faza) * (n - 1)
        return [przyciemnij(kolor, max(0.0, 1 - abs(i - poz) / 1.5)) for i in range(n)]
    return [CZARNY] * n


def klatka(u: dict, tel: Telemetria, t: float) -> list[Kolor]:
    """Colours of all LEDs at time t (seconds). Brightness is not applied."""
    n = u["liczba_diod"]
    s = u["stany"]

    if not tel.gra_aktywna:
        return _bezczynnosc(u, t)

    pit = s["pit_limiter"]
    if tel.pit_limiter and pit["wlaczony"]:
        kolor = hex_na_kolor(pit["kolor"])
        faza = _miga(t, pit["miganie_hz"])
        if pit["wzor"] == "naprzemiennie":
            return [kolor if (i % 2 == 0) == faza else CZARNY for i in range(n)]
        if pit["wzor"] == "polowki":
            return [kolor if (i < n / 2) == faza else CZARNY for i in range(n)]
        return [kolor if faza else CZARNY] * n

    obroty = min(1.0, max(0.0, tel.obroty))
    zb = s["zmiana_biegu"]
    if zb["wlaczony"] and obroty >= zb["prog"] / 100.0:
        wynik = [hex_na_kolor(zb["kolor"]) if _miga(t, zb["miganie_hz"]) else CZARNY] * n
    else:
        wynik = _pasek_obrotow(u, obroty)

    flaga = {"zolta": s["flaga_zolta"], "niebieska": s["flaga_niebieska"]}.get(tel.flaga or "")
    if flaga and flaga["wlaczony"]:
        kolor = hex_na_kolor(flaga["kolor"]) if _miga(t, flaga["miganie_hz"]) else CZARNY
        skrajne = s["flagi_diody_skrajne"]
        if skrajne <= 0 or 2 * skrajne >= n:
            wynik = [kolor] * n
        else:
            for i in list(range(skrajne)) + list(range(n - skrajne, n)):
                wynik[i] = kolor

    # spotter on top of everything - a car alongside matters more than revs and flags
    sp = s["spotter"]
    if sp["wlaczony"] and (tel.auto_lewo or tel.auto_prawo):
        lewo, prawo = tel.auto_lewo, tel.auto_prawo
        if sp["zamien_strony"]:
            lewo, prawo = prawo, lewo
        kolor = hex_na_kolor(sp["kolor"]) if _miga(t, sp["miganie_hz"]) else CZARNY
        k = max(1, min(sp["diody"], n // 2))
        if lewo:
            for i in range(k):
                wynik[i] = kolor
        if prawo:
            for i in range(n - k, n):
                wynik[i] = kolor
    return wynik


# ===================================================== start-up animation
ANIMACJE_STARTU = {
    "fala": "biała fala od brzegów, potem kolory obrotów",
    "tecza": "tęcza przesuwająca się po pasku",
    "wylaczona": "bez animacji",
}
CZAS_ANIMACJI_S = 2.6
BIALY: Kolor = (255, 255, 255)


def _gladko(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _hsv(h: float) -> Kolor:
    h = (h % 1.0) * 6
    i, f = int(h), h - int(h)
    k = [(1, f, 0), (1 - f, 1, 0), (0, 1, f), (0, 1 - f, 1), (f, 0, 1), (1, 0, 1 - f)][i % 6]
    return tuple(round(255 * c) for c in k)  # type: ignore[return-value]


def animacja_startu(u: dict, t: float) -> list[Kolor] | None:
    """Start-up animation frame at time t from its start, or None once it has finished."""
    styl = u.get("animacja_startu", "fala")
    if styl == "wylaczona" or t < 0 or t >= CZAS_ANIMACJI_S:
        return None
    n = u["liczba_diod"]
    if styl == "tecza":
        jasnosc = _gladko(t / 0.4) * (1 - _gladko((t - 1.9) / 0.7))
        return [przyciemnij(_hsv(i / max(n, 1) * 0.9 - t * 0.55), jasnosc) for i in range(n)]

    # "fala" (wave): white LEDs light up from the edges to the centre, then change to the
    # rev colours (from the settings), a moment of full strip, then fade out
    kroki = kroki_diod(n, "do_srodka")
    ile = max(kroki) + 1
    kolory = [hex_na_kolor(k) for k in u["kolory"]]
    wynik = []
    for i, krok in enumerate(kroki):
        zapal = _gladko((t - 0.75 * krok / ile) / 0.18)          # 0..0.9 s - wave
        w_kolor = _gladko((t - 0.95 - 0.25 * krok / ile) / 0.35)  # 0.95..1.55 s - colours
        zgas = 1 - _gladko((t - 1.9) / 0.7)                       # 1.9..2.6 s - fade out
        wynik.append(przyciemnij(mieszaj(BIALY, kolory[i], w_kolor), zapal * zgas))
    return wynik


def z_jasnoscia(kolory: list[Kolor], jasnosc_proc: float) -> list[Kolor]:
    return [przyciemnij(k, jasnosc_proc / 100.0) for k in kolory]


def komenda_leds(kolory: list[Kolor]) -> str:
    """The line to send to the ESP32, e.g. 'LEDS 00FF00FF0000...'."""
    return "LEDS " + "".join("{:02X}{:02X}{:02X}".format(*k) for k in kolory)
