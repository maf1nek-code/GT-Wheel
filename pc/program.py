# -*- coding: utf-8 -*-
"""
Kierownica GT - ustawienia programu, autostart z Windows, ikona przy zegarze
(zasobnik systemowy) i wirtualny kontroler do gier.

Wszystko tutaj jest opcjonalne: jesli brakuje biblioteki (pystray / Pillow /
vJoy) albo system nie jest Windows, program dziala dalej bez tej funkcji.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

WERSJA_PROGRAMU = "2.0"
KATALOG = Path(__file__).resolve().parent
PLIK_USTAWIEN_PROGRAMU = KATALOG / "ustawienia.json"
NAZWA_W_AUTOSTARCIE = "KierownicaGT"
KLUCZ_AUTOSTARTU = r"Software\Microsoft\Windows\CurrentVersion\Run"

KONTROLERY = {
    "auto": "Automatycznie (vJoy, a gdy go nie ma – pad Xbox)",
    "vjoy": "vJoy",
    "xbox": "Pad Xbox 360",
    "brak": "Wyłączony",
}

DOMYSLNE = {
    "po_zamknieciu": "tlo",        # "tlo" - dzialaj przy zegarze, "zakoncz" - zamknij program
    "okno_przy_autostarcie": False,
    "kontroler": "auto",
    "vjoy_id": 1,
    "diody_w_grze": True,
    "powiadomienia": True,
}


# ============================================================ ustawienia
def popraw(u) -> dict:
    wynik = dict(DOMYSLNE)
    if not isinstance(u, dict):
        return wynik
    if u.get("po_zamknieciu") in ("tlo", "zakoncz"):
        wynik["po_zamknieciu"] = u["po_zamknieciu"]
    if u.get("kontroler") in KONTROLERY:
        wynik["kontroler"] = u["kontroler"]
    vid = u.get("vjoy_id")
    if isinstance(vid, int) and not isinstance(vid, bool) and 1 <= vid <= 16:
        wynik["vjoy_id"] = vid
    for k in ("okno_przy_autostarcie", "diody_w_grze", "powiadomienia"):
        if isinstance(u.get(k), bool):
            wynik[k] = u[k]
    return wynik


def wczytaj() -> dict:
    try:
        return popraw(json.loads(PLIK_USTAWIEN_PROGRAMU.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return dict(DOMYSLNE)


def zapisz(u: dict) -> None:
    tmp = PLIK_USTAWIEN_PROGRAMU.with_suffix(".tmp")
    tmp.write_text(json.dumps(popraw(u), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PLIK_USTAWIEN_PROGRAMU)


# ============================================================= autostart
def autostart_dostepny() -> bool:
    return sys.platform == "win32"


def polecenie_autostartu() -> str:
    """pythonw.exe (bez czarnego okna) + konfigurator.py --tlo."""
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else python
    return f'"{exe}" "{KATALOG / "konfigurator.py"}" --tlo'


def autostart_wlaczony() -> bool:
    if not autostart_dostepny():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KLUCZ_AUTOSTARTU) as k:
            wartosc, _ = winreg.QueryValueEx(k, NAZWA_W_AUTOSTARCIE)
            return bool(wartosc)
    except OSError:
        return False


def ustaw_autostart(wlacz: bool) -> None:
    """Dopisuje / usuwa program z autostartu biezacego uzytkownika (bez uprawnien admina)."""
    if not autostart_dostepny():
        raise ValueError("Autostart działa tylko w Windows.")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KLUCZ_AUTOSTARTU, 0,
                        winreg.KEY_SET_VALUE) as k:
        if wlacz:
            winreg.SetValueEx(k, NAZWA_W_AUTOSTARCIE, 0, winreg.REG_SZ, polecenie_autostartu())
        else:
            try:
                winreg.DeleteValue(k, NAZWA_W_AUTOSTARCIE)
            except FileNotFoundError:
                pass


def otworz_folder(sciezka: Path = KATALOG) -> None:
    if sys.platform == "win32":
        os.startfile(str(sciezka))   # noqa: S606 - folder programu
    else:
        raise ValueError("Otwieranie folderu działa tylko w Windows.")


# ============================================================= kontroler
def utworz_kontroler(rodzaj: str, vjoy_id: int):
    """Zwraca (kontroler, opis, blad). Nigdy nie konczy programu."""
    import kierownica as k
    bledy = []
    if rodzaj == "brak":
        return k.Backend(), "wyłączony", None
    if rodzaj in ("auto", "vjoy"):
        try:
            b = k.VJoyBackend(vjoy_id)
            return b, f"vJoy (urządzenie {vjoy_id})", None
        except Exception as exc:  # brak sterownika, urzadzenie zajete, brak biblioteki
            bledy.append(f"vJoy: {exc}")
            if rodzaj == "vjoy":
                return k.Backend(), "brak", ("Nie udało się uruchomić vJoy – zainstaluj sterownik "
                                             f"i włącz urządzenie {vjoy_id} w „Configure vJoy”.")
    try:
        return k.XboxBackend(), "pad Xbox 360", None
    except Exception as exc:
        bledy.append(f"Xbox: {exc}")
    return k.Backend(), "brak", ("Nie znaleziono ani vJoy, ani sterownika pada Xbox (ViGEmBus). "
                                 "Przyciski nie trafią do gry.")


# ======================================================== ikona przy zegarze
class Tacka:
    """Ikona w zasobniku systemowym. Gdy brakuje pystray/Pillow - dostepna = False."""

    def __init__(self, otworz, zakoncz, przelacz_diody, diody_wlaczone) -> None:
        self.dostepna = False
        self._ikona = None
        self._otworz, self._zakoncz = otworz, zakoncz
        self._przelacz_diody, self._diody_wlaczone = przelacz_diody, diody_wlaczone
        self._tekst = "Kierownica GT"
        self._stan = "szukam"
        try:
            if importlib.util.find_spec("pystray") is None or \
                    importlib.util.find_spec("PIL") is None:
                return
        except (ImportError, ValueError):
            return
        if sys.platform != "win32" and not os.environ.get("DISPLAY"):
            return
        self.dostepna = True

    # rysowana ikona: czerwony kwadrat z kierownica + kropka stanu polaczenia
    @staticmethod
    def _obrazek(stan: str):
        from PIL import Image, ImageDraw
        r = 64
        im = Image.new("RGBA", (r, r), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((2, 2, r - 3, r - 3), radius=14, fill=(255, 61, 46, 255))
        d.ellipse((9, 9, 55, 55), outline="white", width=6)          # obrecz
        d.line((12, 32, 52, 32), fill="white", width=6)                # szprychy
        d.line((32, 32, 32, 53), fill="white", width=6)
        d.ellipse((24, 24, 40, 40), fill="white")                      # piasta
        kolor = {"polaczono": (34, 197, 94), "zajety": (240, 68, 68)}.get(stan, (245, 165, 36))
        if stan == "rozlaczono":
            kolor = (140, 148, 160)
        d.ellipse((42, 42, 62, 62), fill=kolor + (255,), outline=(20, 20, 20, 255), width=3)
        return im

    def start(self) -> None:
        if not self.dostepna:
            return
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: self._tekst, None, enabled=False),
            pystray.MenuItem("Otwórz konfigurator", lambda: self._otworz(), default=True),
            pystray.MenuItem("Diody w czasie gry", lambda: self._przelacz_diody(),
                             checked=lambda _: self._diody_wlaczone()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Zakończ", lambda: self._zakoncz()),
        )
        self._ikona = pystray.Icon("KierownicaGT", self._obrazek(self._stan), "Kierownica GT", menu)
        threading.Thread(target=self._ikona.run, daemon=True).start()

    def stan(self, stan: str, tekst: str) -> None:
        self._tekst = f"Kierownica GT – {tekst}"
        if not self._ikona:
            return
        try:
            self._ikona.title = self._tekst[:120]
            if stan != self._stan:
                self._stan = stan
                self._ikona.icon = self._obrazek(stan)
            self._ikona.update_menu()
        except Exception:
            pass

    def powiadom(self, tekst: str, tytul: str = "Kierownica GT") -> None:
        if not self._ikona:
            return
        try:
            self._ikona.notify(tekst, tytul)
        except Exception:
            pass

    def odswiez_menu(self) -> None:
        if self._ikona:
            try:
                self._ikona.update_menu()
            except Exception:
                pass

    def zatrzymaj(self) -> None:
        if self._ikona:
            try:
                self._ikona.stop()
            except Exception:
                pass
