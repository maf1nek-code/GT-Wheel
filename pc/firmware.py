# -*- coding: utf-8 -*-
"""
Kierownica GT - aktualizacja firmware ESP32 z konfiguratora.

* sprawdz_github()  - najnowsze wydanie "fw-<wersja>" w repozytorium projektu
                      (buduje je GitHub Actions: .github/workflows/firmware.yml)
* pobierz()         - pobiera plik .bin
* rozpoznaj()       - sprawdza plik i zwraca adres w pamieci flash
* wgraj()           - wgrywa przez esptool (to samo narzedzie, ktorego uzywa Arduino IDE)
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPOZYTORIUM = "maf1nek-code/Kierownica-gt"
API_WYDAN = f"https://api.github.com/repos/{REPOZYTORIUM}/releases?per_page=30"
USER_AGENT = "KierownicaGT-konfigurator"
MAX_ROZMIAR = 8 * 1024 * 1024
MAGIA_OBRAZU = 0xE9             # pierwszy bajt obrazu ESP32 (bootloader / program)
ADRES_BOOTLOADERA = 0x1000      # ESP32 (klasyczny)
ADRES_PROGRAMU = 0x10000        # domyslny podzial pamieci "ESP32 Dev Module"


class BladFirmware(Exception):
    """Blad z komunikatem po polsku, do pokazania uzytkownikowi."""


def wersja_krotka(tekst: str | None) -> tuple:
    """'1.10' -> (1, 10); smieci -> ()."""
    liczby = re.findall(r"\d+", str(tekst or ""))
    return tuple(int(x) for x in liczby[:4])


def nowsza(a: str | None, b: str | None) -> bool:
    """Czy wersja a jest nowsza niz b."""
    return wersja_krotka(a) > wersja_krotka(b)


def _zapytanie(url: str, akceptuj: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": akceptuj})


def sprawdz_github(limit_s: float = 8.0) -> dict | None:
    """Najnowszy firmware z wydan GitHuba albo None, gdy zadnego jeszcze nie ma."""
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
            "url": plik["browser_download_url"],
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
    """Adres, pod ktory nalezy wgrac plik. Odrzuca pliki, ktore nie sa firmware ESP32."""
    if len(dane) > MAX_ROZMIAR:
        raise BladFirmware("Plik jest za duży jak na firmware.")
    # plik "merged" (Arduino IDE 2: Szkic -> Eksportuj skompilowany plik binarny,
    # albo wydanie z GitHuba): bootloader + podzial pamieci + program, od adresu 0
    if len(dane) > ADRES_PROGRAMU + 1024 and dane[0] == 0xFF and \
            dane[ADRES_BOOTLOADERA] == MAGIA_OBRAZU and dane[ADRES_PROGRAMU] == MAGIA_OBRAZU:
        return 0x0
    # sam program (kierownica_gt.ino.bin)
    if len(dane) > 64 * 1024 and dane[0] == MAGIA_OBRAZU:
        return ADRES_PROGRAMU
    raise BladFirmware("To nie wygląda na firmware ESP32. Wybierz plik "
                       "kierownica_gt.ino.merged.bin albo kierownica_gt.ino.bin.")


def esptool_dostepny() -> bool:
    return importlib.util.find_spec("esptool") is not None


def _podpowiedz(log: str) -> str:
    tekst = log.lower()
    if "failed to connect" in tekst or "wrong boot mode" in tekst or "timed out waiting" in tekst:
        return ("Nie udało się połączyć z ESP32. Przytrzymaj przycisk BOOT na płytce, kliknij "
                "„Aktualizuj” jeszcze raz i puść BOOT, gdy pojawi się „Łączenie”.")
    if "could not open port" in tekst or "permissionerror" in tekst or "access is denied" in tekst:
        return ("Nie można otworzyć portu – kierownica jest odłączona albo port zajmuje inny program "
                "(zamknij Kierownica_GT.bat i Serial Monitor).")
    if "a fatal error occurred" in tekst:
        return "esptool zgłosił błąd – szczegóły w dzienniku poniżej."
    return "Wgrywanie nie powiodło się – szczegóły w dzienniku poniżej."


def wgraj(port: str, plik: str, adres: int, postep, linia_logu) -> None:
    """Wgrywa plik. postep(procent, tekst) i linia_logu(tekst) sa wolane w trakcie."""
    if not esptool_dostepny():
        raise BladFirmware("Brak narzędzia esptool. Uruchom ponownie Konfigurator_GT.bat – "
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
