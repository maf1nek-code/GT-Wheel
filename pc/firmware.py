# -*- coding: utf-8 -*-
"""
GT Wheel - ESP32 firmware updates from the configurator.

* sprawdz_github()  - latest "fw-<version>" release in the project repository
                      (built by GitHub Actions: .github/workflows/firmware.yml)
* pobierz()         - downloads the .bin file
* rozpoznaj()       - checks the file and returns its flash address
* wgraj()           - uploads it with esptool (the same tool the Arduino IDE uses)
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPOZYTORIUM = "maf1nek-code/GT-Wheel"
API_WYDAN = f"https://api.github.com/repos/{REPOZYTORIUM}/releases?per_page=30"
USER_AGENT = "KierownicaGT-konfigurator"
MAX_ROZMIAR = 8 * 1024 * 1024
MAGIA_OBRAZU = 0xE9             # first byte of an ESP32 image (bootloader / program)
ADRES_BOOTLOADERA = 0x1000      # ESP32 (classic)
ADRES_PROGRAMU = 0x10000        # default partition table of the "ESP32 Dev Module"


class BladFirmware(Exception):
    """An error with a Polish message, meant to be shown to the user."""


def wersja_krotka(tekst: str | None) -> tuple:
    """'1.10' -> (1, 10); garbage -> ()."""
    liczby = re.findall(r"\d+", str(tekst or ""))
    return tuple(int(x) for x in liczby[:4])


def nowsza(a: str | None, b: str | None) -> bool:
    """Whether version a is newer than b."""
    return wersja_krotka(a) > wersja_krotka(b)


def _zapytanie(url: str, akceptuj: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": akceptuj})


def sprawdz_github(limit_s: float = 8.0) -> dict | None:
    """The latest firmware from the GitHub releases, or None if there is none yet."""
    try:
        with urllib.request.urlopen(_zapytanie(API_WYDAN, "application/vnd.github+json"),
                                    timeout=limit_s) as odp:
            wydania = json.loads(odp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise BladFirmware("GitHub chwilowo ogranicza zapytania. Spróbuj za kilka minut.") from exc
        raise BladFirmware(f"GitHub odpowiedział błędem {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BladFirmware("Brak połączenia z internetem (GitHub). Możesz wgrać plik .bin "
                           "z dysku.") from exc
    except ValueError as exc:
        raise BladFirmware("GitHub zwrócił niepoprawne dane.") from exc

    najlepsze = None
    for w in wydania if isinstance(wydania, list) else []:
        tag = str(w.get("tag_name", ""))
        if w.get("draft") or not tag.startswith("fw-"):
            continue
        plik = next((a for a in w.get("assets", [])
                     if str(a.get("name", "")).endswith("-merged.bin")), None)
        if not plik:
            continue
        kandydat = {
            "wersja": tag[3:],
            "nazwa": plik["name"],
            # download through the API (with Accept: application/octet-stream) - this also works
            # where direct github.com/.../releases/download links are blocked
            "url": plik.get("url") or plik["browser_download_url"],
            "rozmiar": plik.get("size", 0),
            "data": str(w.get("published_at", ""))[:10],
            "strona": w.get("html_url", ""),
        }
        if najlepsze is None or nowsza(kandydat["wersja"], najlepsze["wersja"]):
            najlepsze = kandydat
    return najlepsze


def pobierz(url: str, postep=None, limit_s: float = 30.0) -> bytes:
    if not url.startswith("https://"):
        raise BladFirmware("Niepoprawny adres pliku.")
    try:
        with urllib.request.urlopen(_zapytanie(url, "application/octet-stream"),
                                    timeout=limit_s) as odp:
            calosc = int(odp.headers.get("Content-Length") or 0)
            if calosc > MAX_ROZMIAR:
                raise BladFirmware("Plik firmware jest za duży.")
            dane = bytearray()
            while True:
                kawalek = odp.read(64 * 1024)
                if not kawalek:
                    break
                dane += kawalek
                if len(dane) > MAX_ROZMIAR:
                    raise BladFirmware("Plik firmware jest za duży.")
                if postep and calosc:
                    postep(len(dane) * 100 // calosc)
            return bytes(dane)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BladFirmware("Nie udało się pobrać pliku firmware (internet).") from exc


def rozpoznaj(dane: bytes) -> int:
    """The address to flash the file at. Rejects files that are not ESP32 firmware."""
    if len(dane) > MAX_ROZMIAR:
        raise BladFirmware("Plik jest za duży jak na firmware.")
    # "merged" file (Arduino IDE 2: Sketch -> Export Compiled Binary,
    # or a GitHub release): bootloader + partition table + program, from address 0
    if len(dane) > ADRES_PROGRAMU + 1024 and dane[0] == 0xFF and \
            dane[ADRES_BOOTLOADERA] == MAGIA_OBRAZU and dane[ADRES_PROGRAMU] == MAGIA_OBRAZU:
        return 0x0
    # the program alone (gt_wheel.ino.bin)
    if len(dane) > 64 * 1024 and dane[0] == MAGIA_OBRAZU:
        return ADRES_PROGRAMU
    raise BladFirmware("To nie wygląda na firmware ESP32. Wybierz plik "
                       "gt_wheel.ino.merged.bin albo gt_wheel.ino.bin.")


def esptool_dostepny() -> bool:
    return importlib.util.find_spec("esptool") is not None


def _podpowiedz(log: str) -> str:
    tekst = log.lower()
    if "failed to connect" in tekst or "wrong boot mode" in tekst or "timed out waiting" in tekst:
        return ("Nie udało się połączyć z ESP32. Przytrzymaj przycisk BOOT na płytce, kliknij "
                "„Aktualizuj” jeszcze raz i puść BOOT, gdy pojawi się „Łączenie”.")
    if "could not open port" in tekst or "permissionerror" in tekst or "access is denied" in tekst:
        return ("Nie można otworzyć portu – kierownica jest odłączona albo port zajmuje inny program "
                "(zamknij GT_Wheel.bat i Serial Monitor).")
    if "a fatal error occurred" in tekst:
        return "esptool zgłosił błąd – szczegóły w dzienniku poniżej."
    return "Wgrywanie nie powiodło się – szczegóły w dzienniku poniżej."


def wgraj(port: str, plik: str, adres: int, postep, linia_logu) -> None:
    """Uploads the file. postep(percent, text) and linia_logu(text) are called along the way."""
    if not esptool_dostepny():
        raise BladFirmware("Brak narzędzia esptool. Uruchom ponownie GT_Wheel_Configurator.bat – "
                           "zainstaluje je samo.")
    polecenie = [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", port,
                 "--baud", "460800", "--before", "default_reset", "--after", "hard_reset",
                 "write_flash", "-z", "--flash_mode", "keep", "--flash_freq", "keep",
                 "--flash_size", "keep", hex(adres), plik]
    flagi = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(polecenie, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=flagi)
    except OSError as exc:
        raise BladFirmware(f"Nie udało się uruchomić esptool: {exc}") from exc

    log: list[str] = []
    bufor = b""
    etapy = [("connecting", "Łączenie z ESP32…"), ("erasing", "Kasowanie pamięci…"),
             ("compressed", "Wgrywanie…"), ("writing at", "Wgrywanie…"),
             ("hash of data verified", "Sprawdzanie…"), ("hard resetting", "Restart kierownicy…")]

    def obsluz(tekst: str) -> None:
        tekst = tekst.strip()
        if not tekst:
            return
        if not tekst.startswith("Writing at") or "100 %" in tekst:
            log.append(tekst)
            linia_logu(tekst)
        male = tekst.lower()
        m = re.search(r"\((\d+)\s*%\)", tekst)
        for klucz, opis in etapy:
            if male.startswith(klucz) or klucz in male:
                postep(int(m.group(1)) if m else None, opis)
                break

    assert proc.stdout is not None
    while True:
        kawalek = proc.stdout.read1(256) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
        if not kawalek:
            break
        bufor += kawalek
        czesci = re.split(rb"[\r\n]", bufor)
        bufor = czesci.pop()
        for c in czesci:
            obsluz(c.decode("utf-8", errors="replace"))
    obsluz(bufor.decode("utf-8", errors="replace"))
    kod = proc.wait()
    if kod != 0:
        raise BladFirmware(_podpowiedz("\n".join(log)))
