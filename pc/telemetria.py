# -*- coding: utf-8 -*-
"""
GT Wheel - game telemetry (Windows).

Supported games and data sources:
  * Assetto Corsa              - "acpmf_*" shared memory (built into the game)
  * Assetto Corsa Competizione - "acpmf_*" shared memory (built into the game)
  * Le Mans Ultimate           - rF2SharedMemoryMapPlugin plugin
                                 ("$rFactor2SMMP_*$", the same as for rFactor 2)

The program only READS the data (OpenFileMapping, creates nothing), so it can't
break the game. The result is a Stan (state) object: revs, max revs, gear, pit
limiter, flag and whether the car is on track (not menu / pause / replay).

parsuj_ac() and parsuj_lmu() work on raw bytes only, so they can be checked
without the game (see the test at the bottom: python telemetria.py --test).
"""

from __future__ import annotations

import ctypes
import math
import struct
import sys
import time
from dataclasses import asdict, dataclass

import led_efekty as fx

NAZWY_GIER = {
    "ac": "Assetto Corsa",
    "acc": "Assetto Corsa Competizione",
    "lmu": "Le Mans Ultimate",
}

# process names (lower case) -> game
PROCESY = {
    "acs.exe": "ac",
    "acs_x86.exe": "ac",
    "ac2-win64-shipping.exe": "acc",
    "le mans ultimate.exe": "lmu",
    "lmu.exe": "lmu",
}

SWIEZOSC_S = 1.0     # data unchanged for longer than this = game paused / in menu / closed

# ---------------------------------------------------------------- AC / ACC
AC_FIZYKA = "Local\\acpmf_physics"
AC_GRAFIKA = "Local\\acpmf_graphics"
AC_STATYKA = "Local\\acpmf_static"
AC_LIVE = 2                     # graphics.status: 0 off, 1 replay, 2 driving, 3 pause
AC_FLAGI = {1: "niebieska", 2: "zolta"}

# SPageFilePhysics (AC and ACC share the first fields)
FIZ_PAKIET, FIZ_BIEG, FIZ_RPM, FIZ_PIT = 0, 16, 20, 248
FIZ_DLUGOSC = 252
# SPageFileGraphic: same status; the flag sits elsewhere (ACC has 60 car positions before it)
GRAF_STATUS = 4
GRAF_FLAGA = {"ac": 268, "acc": 1224}
# ACC only: positions of all cars (AC gives only the player's car - no spotter)
ACC_LICZBA_AUT, ACC_POZYCJE, ACC_ID_AUT, ACC_ID_GRACZA = 252, 256, 976, 1216
ACC_MAX_AUT = 60
# SPageFileStatic: maxRpm after 5 wchar[33] strings and 2 wchar[15] strings
STAT_MAX_RPM = 412
STAT_DLUGOSC = 416

# --------------------------------------------------------------------- LMU
RF2_TELEMETRIA = "$rFactor2SMMP_Telemetry$"
RF2_PUNKTACJA = "$rFactor2SMMP_Scoring$"
RF2_MAX_AUT = 128
# header: mVersionUpdateBegin, mVersionUpdateEnd, mBytesUpdatedHint
RF2_NAGLOWEK = 12
# rF2Telemetry: header + mNumVehicles, then rF2VehicleTelemetry[128] (pack 4)
TEL_LICZBA, TEL_POCZATEK, TEL_ROZMIAR = 12, 16, 1888
TEL_ID, TEL_CZAS, TEL_BIEG, TEL_RPM, TEL_MAX_RPM, TEL_OGRANICZNIK = 0, 12, 352, 356, 532, 604
TEL_POTRZEBNE = 608
# rF2Scoring: header + rF2ScoringInfo (548 B) + rF2VehicleScoring[128] (580 B)
SC_INFO = RF2_NAGLOWEK
SC_LICZBA = SC_INFO + 104
SC_FAZA = SC_INFO + 108
SC_ZOLTA_FCY = SC_INFO + 109
SC_SEKTORY = SC_INFO + 110
SC_REALTIME = SC_INFO + 115
SC_AUTA, SC_ROZMIAR = SC_INFO + 548, 580
SCA_ID, SCA_SEKTOR, SCA_GRACZ, SCA_FLAGA = 0, 102, 196, 500
SCA_POZYCJA = 264                 # mPos (3 x double) in scoring - 5 times/s
TEL_POZYCJA = 160                 # mPos (3 x double) in telemetry - usually 50+ times/s

# ------------------------------------------------------------------ spotter
SPOTTER_DLUGOSC_M = 4.8           # cars overlap when the distance along the track is below this
SPOTTER_BOK_M = (0.9, 4.5)        # ...and sideways (min - same car/collision, max - a lane further away)
SPOTTER_WYSOKOSC_M = 3.0          # overpasses on the track (e.g. Suzuka)
# the cross product sign for a car on the LEFT depends on the game's coordinate system
# (right-handed in AC/ACC, left-handed in rFactor 2 / LMU); the settings also
# have "swap sides" in case a game comes out reversed
LEWO_GDY_UJEMNY = {"acc": True, "lmu": False}
RF2_FAZA_FCY = 6
RF2_FLAGA_NIEBIESKA = 6
RF2_SEKTOR_ZOLTY = 11


@dataclass
class Stan:
    gra: str | None = None        # "ac" / "acc" / "lmu" or None
    aktywna: bool = False         # on track
    rpm: float = 0.0
    max_rpm: float = 0.0
    bieg: int | None = None       # -1 = R, 0 = N, 1.. = gear
    pit_limiter: bool = False
    flaga: str | None = None      # None / "zolta" (yellow) / "niebieska" (blue)
    auto_lewo: bool = False       # spotter: car alongside on the left
    auto_prawo: bool = False      # spotter: car alongside on the right
    spotter: bool = False         # whether the game provides other cars' positions
    opis: str = ""                # message for the user

    @property
    def nazwa_gry(self) -> str:
        return NAZWY_GIER.get(self.gra or "", "")

    @property
    def obroty(self) -> float:
        if self.max_rpm <= 0:
            return 0.0
        return min(1.0, max(0.0, self.rpm / self.max_rpm))

    def telemetria(self) -> fx.Telemetria:
        return fx.Telemetria(obroty=self.obroty, gra_aktywna=self.aktywna,
                             pit_limiter=self.pit_limiter,
                             flaga=self.flaga if self.aktywna else None,
                             auto_lewo=self.auto_lewo and self.aktywna,
                             auto_prawo=self.auto_prawo and self.aktywna)

    def slownik(self) -> dict:
        d = asdict(self)
        d["nazwa"] = self.nazwa_gry
        d["obroty"] = round(self.obroty, 4)
        d["rpm"] = round(self.rpm)
        d["max_rpm"] = round(self.max_rpm)
        return d


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _f64(b: bytes, o: int) -> float:
    return struct.unpack_from("<d", b, o)[0]


def _rozsadne_rpm(x: float) -> bool:
    return x == x and 0 <= x <= 30000          # x == x: rejects NaN


# =============================================================== spotter
class Spotter:
    """Whether another car is alongside the player (on the left / on the right).

    The driving direction comes from the player's own movement (position change), so it
    doesn't depend on how a game stores the car's rotation. When stationary (e.g. on the
    grid, in the pits) the spotter stays quiet.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._kotwica = None
        self._kotwica_czas = 0.0
        self._kierunek = None

    def oblicz(self, gracz: tuple, inni: list[tuple], lewo_gdy_ujemny: bool,
               teraz: float) -> tuple[bool, bool]:
        gx, gy, gz = gracz
        if self._kotwica is None:
            self._kotwica, self._kotwica_czas = gracz, teraz
            return False, False
        dx, dz = gx - self._kotwica[0], gz - self._kotwica[2]
        droga = math.hypot(dx, dz)
        if droga > 30.0:                      # teleport (back to the pits, restart)
            self.reset()
            return False, False
        if droga >= 0.3:
            self._kierunek = (dx / droga, dz / droga)
            self._kotwica, self._kotwica_czas = gracz, teraz
        if self._kierunek is None or teraz - self._kotwica_czas > 1.0:
            return False, False               # stopped or moving very slowly
        fx_, fz = self._kierunek
        lewo = prawo = False
        for x, y, z in inni:
            ox, oy, oz = x - gx, y - gy, z - gz
            if abs(oy) > SPOTTER_WYSOKOSC_M:
                continue
            wzdluz = ox * fx_ + oz * fz
            bok = fx_ * oz - fz * ox
            if abs(wzdluz) < SPOTTER_DLUGOSC_M and SPOTTER_BOK_M[0] < abs(bok) < SPOTTER_BOK_M[1]:
                if (bok < 0) == lewo_gdy_ujemny:
                    lewo = True
                else:
                    prawo = True
        return lewo, prawo


def pozycje_acc(graf: bytes) -> tuple[tuple | None, list[tuple]]:
    """(player position, positions of the other cars) from ACC's SPageFileGraphic."""
    n = _i32(graf, ACC_LICZBA_AUT)
    gracz_id = _i32(graf, ACC_ID_GRACZA)
    if not 0 <= n <= ACC_MAX_AUT:
        return None, []
    gracz, inni = None, []
    for i in range(n):
        poz = struct.unpack_from("<3f", graf, ACC_POZYCJE + i * 12)
        if not all(math.isfinite(v) for v in poz):
            continue
        if _i32(graf, ACC_ID_AUT + i * 4) == gracz_id:
            gracz = poz
        else:
            inni.append(poz)
    return gracz, inni


# =============================================================== parsing
def parsuj_ac(gra: str, fiz: bytes, graf: bytes, stat: bytes) -> Stan:
    """AC/ACC data (bytes from shared memory) -> Stan (without 'aktywna', which comes from freshness)."""
    rpm = float(_i32(fiz, FIZ_RPM))
    max_rpm = float(_i32(stat, STAT_MAX_RPM))
    bieg = _i32(fiz, FIZ_BIEG) - 1              # in AC: 0 = R, 1 = N, 2 = 1st gear
    status = _i32(graf, GRAF_STATUS)
    flaga = AC_FLAGI.get(_i32(graf, GRAF_FLAGA[gra]))
    pit = _i32(fiz, FIZ_PIT) != 0
    if not _rozsadne_rpm(rpm) or not -1 <= bieg <= 12 or not 0 <= status <= 3:
        return Stan(gra=gra, opis="Nieznany format danych z gry.")
    if not _rozsadne_rpm(max_rpm) or max_rpm < 1000:
        max_rpm = 0.0
    return Stan(gra=gra, aktywna=status == AC_LIVE, rpm=rpm, max_rpm=max_rpm, bieg=bieg,
                pit_limiter=pit, flaga=flaga)


def gracz_lmu(punktacja: bytes) -> dict | None:
    """Picks the player's car from the 'Scoring' data. Returns a dict or None."""
    n = _i32(punktacja, SC_LICZBA)
    if not 0 <= n <= RF2_MAX_AUT:
        return None
    for i in range(n):
        o = SC_AUTA + i * SC_ROZMIAR
        if o + SC_ROZMIAR > len(punktacja):
            break
        if punktacja[o + SCA_GRACZ] == 1:
            sektor = struct.unpack_from("<b", punktacja, o + SCA_SEKTOR)[0]
            return {
                "id": _i32(punktacja, o + SCA_ID),
                "sektor": sektor,
                "niebieska": punktacja[o + SCA_FLAGA] == RF2_FLAGA_NIEBIESKA,
            }
    return None


def pozycje_lmu_punktacja(punktacja: bytes, gracz_id: int) -> list[tuple]:
    n = _i32(punktacja, SC_LICZBA)
    wynik = []
    for i in range(max(0, min(n, RF2_MAX_AUT))):
        o = SC_AUTA + i * SC_ROZMIAR
        if o + SC_ROZMIAR > len(punktacja):
            break
        if _i32(punktacja, o + SCA_ID) != gracz_id:
            wynik.append(struct.unpack_from("<3d", punktacja, o + SCA_POZYCJA))
    return wynik


def parsuj_lmu(auto_tel: bytes, punktacja: bytes) -> Stan:
    """auto_tel = the player's rF2VehicleTelemetry bytes, punktacja = the whole Scoring block."""
    gracz = gracz_lmu(punktacja)
    realtime = punktacja[SC_REALTIME] == 1
    rpm = _f64(auto_tel, TEL_RPM)
    max_rpm = _f64(auto_tel, TEL_MAX_RPM)
    bieg = _i32(auto_tel, TEL_BIEG)
    if not _rozsadne_rpm(rpm) or not -1 <= bieg <= 12:
        return Stan(gra="lmu", opis="Nieznany format danych z Le Mans Ultimate.")
    if not _rozsadne_rpm(max_rpm) or max_rpm < 1000:
        max_rpm = 0.0
    flaga = None
    if gracz and gracz["niebieska"]:
        flaga = "niebieska"
    else:
        faza = punktacja[SC_FAZA]
        sektory = struct.unpack_from("<3b", punktacja, SC_SEKTORY)
        s = gracz["sektor"] if gracz else -1
        if faza == RF2_FAZA_FCY or (0 <= s <= 2 and sektory[s] == RF2_SEKTOR_ZOLTY):
            flaga = "zolta"
    return Stan(gra="lmu", aktywna=realtime and gracz is not None, rpm=rpm, max_rpm=max_rpm,
                bieg=bieg, pit_limiter=auto_tel[TEL_OGRANICZNIK] != 0, flaga=flaga)


# ===================================================== memory access (Windows)
if sys.platform == "win32":
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    FILE_MAP_READ = 0x0004
    TH32CS_SNAPPROCESS = 0x00000002

    class _MBI(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                    ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD)]

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    _k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.OpenFileMappingW.restype = wintypes.HANDLE
    _k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.c_size_t]
    _k32.MapViewOfFile.restype = ctypes.c_void_p
    _k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    _k32.UnmapViewOfFile.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
    _k32.VirtualQuery.restype = ctypes.c_size_t
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _k32.Process32FirstW.restype = wintypes.BOOL
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _k32.Process32NextW.restype = wintypes.BOOL
    _ZLY_UCHWYT = ctypes.c_void_p(-1).value

    def uruchomione_procesy() -> set[str]:
        snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == _ZLY_UCHWYT:
            return set()
        wynik = set()
        try:
            e = _PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(e)
            ok = _k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                wynik.add(e.szExeFile.lower())
                ok = _k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            _k32.CloseHandle(snap)
        return wynik
else:
    def uruchomione_procesy() -> set[str]:
        return set()


class Mapa:
    """The game's existing shared memory, opened read-only."""

    def __init__(self, nazwa: str) -> None:
        self.nazwa = nazwa
        self._uchwyt = None
        self._adres = None
        self.rozmiar = 0

    @property
    def otwarta(self) -> bool:
        return self._adres is not None

    def otworz(self) -> bool:
        if self._adres is not None:
            return True
        if sys.platform != "win32":
            return False
        uchwyt = _k32.OpenFileMappingW(FILE_MAP_READ, False, self.nazwa)
        if not uchwyt:
            return False                   # the game hasn't created the data yet
        adres = _k32.MapViewOfFile(uchwyt, FILE_MAP_READ, 0, 0, 0)
        if not adres:
            _k32.CloseHandle(uchwyt)
            return False
        mbi = _MBI()
        if not _k32.VirtualQuery(ctypes.c_void_p(adres), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            _k32.UnmapViewOfFile(ctypes.c_void_p(adres))
            _k32.CloseHandle(uchwyt)
            return False
        self._uchwyt, self._adres, self.rozmiar = uchwyt, adres, int(mbi.RegionSize)
        return True

    def czytaj(self, przesuniecie: int, ile: int) -> bytes | None:
        if self._adres is None or przesuniecie < 0 or przesuniecie + ile > self.rozmiar:
            return None
        return ctypes.string_at(self._adres + przesuniecie, ile)

    def zamknij(self) -> None:
        if self._adres is not None:
            _k32.UnmapViewOfFile(ctypes.c_void_p(self._adres))
            self._adres = None
        if self._uchwyt:
            _k32.CloseHandle(self._uchwyt)
            self._uchwyt = None
        self.rozmiar = 0


# ================================================================ reader
class Czytnik:
    """Detects the game and reads its telemetry. Call odczyt() several dozen times a second."""

    def __init__(self) -> None:
        self.windows = sys.platform == "win32"
        self._ac = [Mapa(AC_FIZYKA), Mapa(AC_GRAFIKA), Mapa(AC_STATYKA)]
        self._rf2 = [Mapa(RF2_TELEMETRIA), Mapa(RF2_PUNKTACJA)]
        self._gra_procesu: str | None = None
        self._kiedy_procesy = -999.0
        self._probny_czas = -999.0
        self._znacznik = None
        self._znacznik_czas = 0.0
        self._max_widziane = 0.0
        self._ostatnia_gra: str | None = None
        self._punktacja = b""
        self._punktacja_czas = -999.0
        self._spotter = Spotter()

    def zamknij(self) -> None:
        for m in self._ac + self._rf2:
            m.zamknij()

    # -------------------------------------------------------------------
    def odczyt(self) -> Stan:
        if not self.windows:
            return Stan(opis="Telemetria z gier działa tylko w Windows.")
        teraz = time.monotonic()
        if teraz - self._kiedy_procesy > 2.0:
            self._kiedy_procesy = teraz
            procesy = uruchomione_procesy()
            self._gra_procesu = next((PROCESY[p] for p in procesy if p in PROCESY), None)

        gra = self._gra_procesu
        if gra in ("ac", "acc"):
            self._zamknij(self._rf2)
            stan = self._czytaj_ac(gra, teraz)
        elif gra == "lmu":
            self._zamknij(self._ac)
            stan = self._czytaj_lmu(teraz)
        else:
            stan = self._bez_procesu(teraz)

        if stan.gra != self._ostatnia_gra:
            self._ostatnia_gra = stan.gra
            self._max_widziane = 0.0
            self._spotter.reset()
        # max revs: from the game, or the highest seen when the game doesn't provide them
        if stan.aktywna:
            self._max_widziane = max(self._max_widziane, stan.rpm)
        if stan.max_rpm <= 0 and self._max_widziane >= 1000:
            stan.max_rpm = self._max_widziane
        return stan

    @staticmethod
    def _zamknij(mapy: list[Mapa]) -> None:
        for m in mapy:
            m.zamknij()

    def _swieze(self, znacznik, teraz: float) -> bool:
        """Whether the data is changing (the game isn't paused / in a menu / closed)."""
        if znacznik != self._znacznik:
            self._znacznik = znacznik
            self._znacznik_czas = teraz
        return teraz - self._znacznik_czas < SWIEZOSC_S

    def _bez_procesu(self, teraz: float) -> Stan:
        """No known process name found - try the data anyway (e.g. a different game executable name)."""
        brak = Stan(opis="Nie wykryto gry. Obsługiwane: Assetto Corsa, Assetto Corsa "
                         "Competizione, Le Mans Ultimate.")
        if teraz - self._probny_czas < 2.0 and not any(m.otwarta for m in self._ac + self._rf2):
            return brak
        self._probny_czas = teraz
        for gra, mapy, czytaj in (("ac", self._ac, lambda: self._czytaj_ac("ac", teraz)),
                                  ("lmu", self._rf2, lambda: self._czytaj_lmu(teraz))):
            if all(m.otworz() for m in mapy):
                stan = czytaj()
                if stan.aktywna or teraz - self._znacznik_czas < 3.0:
                    return stan
            self._zamknij(mapy)       # stale data - release it so the system can free it
        return brak

    # ------------------------------------------------------------- AC/ACC
    def _czytaj_ac(self, gra: str, teraz: float) -> Stan:
        nazwa = NAZWY_GIER[gra]
        if not all(m.otworz() for m in self._ac):
            return Stan(gra=gra, opis=f"{nazwa} działa – czekam na dane (wejdź na tor).")
        fiz = self._ac[0].czytaj(0, FIZ_DLUGOSC)
        graf = self._ac[1].czytaj(0, max(GRAF_FLAGA[gra], ACC_ID_GRACZA) + 4 if gra == "acc"
                                  else GRAF_FLAGA[gra] + 4)
        stat = self._ac[2].czytaj(0, STAT_DLUGOSC)
        if fiz is None or graf is None or stat is None:
            return Stan(gra=gra, opis=f"Nieznany format danych z gry {nazwa}.")
        stan = parsuj_ac(gra, fiz, graf, stat)
        swieze = self._swieze(("ac", _i32(fiz, FIZ_PAKIET)), teraz)
        stan.aktywna = stan.aktywna and swieze
        if gra == "acc" and stan.aktywna:
            stan.spotter = True
            gracz, inni = pozycje_acc(graf)
            if gracz is not None:
                stan.auto_lewo, stan.auto_prawo = self._spotter.oblicz(
                    gracz, inni, LEWO_GDY_UJEMNY["acc"], teraz)
        if not stan.opis:
            stan.opis = f"{nazwa}: jazda" if stan.aktywna else f"{nazwa}: menu, pauza lub powtórka"
        return stan

    # ------------------------------------------------------------------ LMU
    def _spojny_odczyt(self, mapa: Mapa, ile: int) -> bytes | None:
        """A copy of the rF2 data taken while the game isn't writing it (version counter begin == end)."""
        for _ in range(4):
            dane = mapa.czytaj(0, min(ile, mapa.rozmiar))
            if dane is None or len(dane) < RF2_NAGLOWEK:
                return None
            if _u32(dane, 0) == _u32(dane, 4):
                return dane
        return None

    def _czytaj_lmu(self, teraz: float) -> Stan:
        nazwa = NAZWY_GIER["lmu"]
        if not all(m.otworz() for m in self._rf2):
            return Stan(gra="lmu", opis=f"{nazwa} działa, ale nie udostępnia danych – włącz "
                                        "wtyczkę rF2SharedMemoryMapPlugin (instrukcja w README).")
        # scoring changes ~5 times a second - no need to read it more often
        if teraz - self._punktacja_czas > 0.2 or not self._punktacja:
            pkt = self._spojny_odczyt(self._rf2[1], SC_AUTA + RF2_MAX_AUT * SC_ROZMIAR)
            if pkt is not None:
                self._punktacja, self._punktacja_czas = pkt, teraz
        if not self._punktacja:
            return Stan(gra="lmu", opis=f"{nazwa}: czekam na dane…")
        gracz = gracz_lmu(self._punktacja)
        if gracz is None:
            return Stan(gra="lmu", opis=f"{nazwa}: menu (brak auta gracza).")

        tel = self._rf2[0]
        for _ in range(4):
            nagl = tel.czytaj(0, TEL_POCZATEK)
            if nagl is None:
                return Stan(gra="lmu", opis=f"Nieznany format danych z gry {nazwa}.")
            n = _i32(nagl, TEL_LICZBA)
            if not 0 <= n <= RF2_MAX_AUT:
                return Stan(gra="lmu", opis=f"Nieznany format danych z gry {nazwa}.")
            auto = None
            inni = []
            for i in range(n):
                o = TEL_POCZATEK + i * TEL_ROZMIAR
                kawalek = tel.czytaj(o, TEL_POZYCJA + 24)
                if kawalek is None:
                    break
                if _i32(kawalek, TEL_ID) == gracz["id"]:
                    auto = tel.czytaj(o, TEL_POTRZEBNE)
                else:
                    inni.append(struct.unpack_from("<3d", kawalek, TEL_POZYCJA))
            koniec = tel.czytaj(0, 8)
            if koniec is not None and _u32(nagl, 0) == _u32(koniec, 4) == _u32(koniec, 0):
                break
        else:
            return Stan(gra="lmu", opis=f"{nazwa}: dane się zmieniają, ponawiam…")
        if auto is None:
            return Stan(gra="lmu", opis=f"{nazwa}: brak telemetrii auta gracza.")
        stan = parsuj_lmu(auto, self._punktacja)
        swieze = self._swieze(("lmu", _f64(auto, TEL_CZAS)), teraz)
        stan.aktywna = stan.aktywna and swieze
        if stan.aktywna:
            stan.spotter = True
            if not inni:   # telemetry has only the player's car - other positions come from scoring (5/s)
                inni = pozycje_lmu_punktacja(self._punktacja, gracz["id"])
            poz = struct.unpack_from("<3d", auto, TEL_POZYCJA)
            inni = [p for p in inni if all(math.isfinite(v) for v in p)]
            if all(math.isfinite(v) for v in poz):
                stan.auto_lewo, stan.auto_prawo = self._spotter.oblicz(
                    poz, inni, LEWO_GDY_UJEMNY["lmu"], teraz)
        if not stan.opis:
            stan.opis = f"{nazwa}: jazda" if stan.aktywna else f"{nazwa}: menu, pauza lub garaż"
        return stan


# ======================================================================= test
def _test() -> None:
    """Checks the parsing on synthetic data laid out like the games' structures."""
    fiz = bytearray(FIZ_DLUGOSC)
    struct.pack_into("<i", fiz, FIZ_PAKIET, 77)
    struct.pack_into("<i", fiz, FIZ_BIEG, 4)          # 3rd gear
    struct.pack_into("<i", fiz, FIZ_RPM, 7200)
    struct.pack_into("<i", fiz, FIZ_PIT, 1)
    stat = bytearray(STAT_DLUGOSC)
    struct.pack_into("<i", stat, STAT_MAX_RPM, 8000)
    for gra in ("ac", "acc"):
        graf = bytearray(GRAF_FLAGA[gra] + 4)
        struct.pack_into("<i", graf, GRAF_STATUS, AC_LIVE)
        struct.pack_into("<i", graf, GRAF_FLAGA[gra], 1)
        s = parsuj_ac(gra, bytes(fiz), bytes(graf), bytes(stat))
        assert (s.aktywna, s.rpm, s.max_rpm, s.bieg, s.pit_limiter, s.flaga) == \
            (True, 7200, 8000, 3, True, "niebieska"), s
        assert abs(s.obroty - 0.9) < 1e-9
    zle = bytearray(fiz)
    struct.pack_into("<i", zle, FIZ_RPM, 999999)
    assert parsuj_ac("ac", bytes(zle), bytes(graf), bytes(stat)).opis

    pkt = bytearray(SC_AUTA + 3 * SC_ROZMIAR)
    struct.pack_into("<i", pkt, SC_LICZBA, 3)
    pkt[SC_REALTIME] = 1
    pkt[SC_FAZA] = 5
    struct.pack_into("<3b", pkt, SC_SEKTORY, 0, RF2_SEKTOR_ZOLTY, 0)
    for i, ident in enumerate((10, 11, 12)):
        o = SC_AUTA + i * SC_ROZMIAR
        struct.pack_into("<i", pkt, o + SCA_ID, ident)
        if ident == 11:
            pkt[o + SCA_GRACZ] = 1
            struct.pack_into("<b", pkt, o + SCA_SEKTOR, 1)
    auto = bytearray(TEL_POTRZEBNE)
    struct.pack_into("<i", auto, TEL_ID, 11)
    struct.pack_into("<i", auto, TEL_BIEG, -1)
    struct.pack_into("<d", auto, TEL_RPM, 3000.0)
    struct.pack_into("<d", auto, TEL_MAX_RPM, 9000.0)
    auto[TEL_OGRANICZNIK] = 1
    s = parsuj_lmu(bytes(auto), bytes(pkt))
    assert (s.aktywna, s.rpm, s.max_rpm, s.bieg, s.pit_limiter, s.flaga) == \
        (True, 3000, 9000, -1, True, "zolta"), s
    assert gracz_lmu(bytes(pkt))["id"] == 11
    pkt[SC_AUTA + SC_ROZMIAR + SCA_FLAGA] = RF2_FLAGA_NIEBIESKA
    assert parsuj_lmu(bytes(auto), bytes(pkt)).flaga == "niebieska"
    # spotter: the player drives along +z; one car 2.5 m to the side at -x and another at +x
    sp = Spotter()
    assert sp.oblicz((0, 0, 0), [], True, 0.0) == (False, False)
    obok = [(-2.5, 0, 1.0)]
    l1 = sp.oblicz((0, 0, 1.0), [(-2.5, 0, 2.0)], True, 0.05)
    l2 = sp.oblicz((0, 0, 2.0), [(2.5, 0, 3.0)], True, 0.10)
    assert l1 != (False, False) and l2 != (False, False) and l1 != l2, (l1, l2)
    assert sp.oblicz((0, 0, 3.0), [(-2.5, 0, 3.0)], False, 0.15) == (l1[1], l1[0])  # the other game = reversed
    assert sp.oblicz((0, 0, 4.0), [(0, 0, 14.0)], True, 0.2) == (False, False)      # far ahead
    assert sp.oblicz((0, 0, 5.0), [(-2.5, 8, 5.0)], True, 0.25) == (False, False)   # overpass
    assert sp.oblicz((0, 0, 5.1), obok, True, 2.0) == (False, False)                # stopped > 1 s
    graf = bytearray(ACC_ID_GRACZA + 4)
    struct.pack_into("<i", graf, ACC_LICZBA_AUT, 2)
    struct.pack_into("<3f", graf, ACC_POZYCJE, 1.0, 2.0, 3.0)
    struct.pack_into("<3f", graf, ACC_POZYCJE + 12, 4.0, 5.0, 6.0)
    struct.pack_into("<2i", graf, ACC_ID_AUT, 7, 9)
    struct.pack_into("<i", graf, ACC_ID_GRACZA, 9)
    assert pozycje_acc(bytes(graf)) == ((4.0, 5.0, 6.0), [(1.0, 2.0, 3.0)])
    print("telemetria: test parsowania OK")


def _podglad() -> None:
    """python telemetria.py  - prints live readings (for checking with the game)."""
    c = Czytnik()
    print("Odczyt telemetrii (Ctrl+C konczy)...")
    try:
        while True:
            s = c.odczyt()
            bieg = {None: "-", -1: "R", 0: "N"}.get(s.bieg, str(s.bieg))
            print(f"\r{s.opis[:60]:<60} | {s.rpm:6.0f}/{s.max_rpm:6.0f} obr | bieg {bieg:>2} | "
                  f"pit {'TAK' if s.pit_limiter else 'nie'} | flaga {s.flaga or '-':<9}",
                  end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        c.zamknij()


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        _podglad()
