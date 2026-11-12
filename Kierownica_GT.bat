@echo off
REM ==========================================================
REM  Kierownica GT - uruchamia most ESP32 -> kontroler do gier
REM  Przy pierwszym uruchomieniu tworzy srodowisko Pythona
REM  (folder pc\.venv) i instaluje potrzebne biblioteki.
REM  Dodatkowe parametry przekazywane sa dalej, np.:
REM     Kierownica_GT.bat --backend xbox
REM     Kierownica_GT.bat --port COM5
REM ==========================================================
setlocal
title Kierownica GT
cd /d "%~dp0pc"

set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto check_deps

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [BLAD] Nie znaleziono Pythona.
    echo Zainstaluj Python 3 ze strony https://www.python.org/downloads/
    echo i podczas instalacji zaznacz "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Tworze srodowisko Pythona (tylko za pierwszym razem)...
%PY% -m venv .venv
if errorlevel 1 (
    echo [BLAD] Nie udalo sie utworzyc srodowiska Pythona.
    pause
    exit /b 1
)

:check_deps
REM Biblioteki instaluja sie ponownie, gdy zmieni sie requirements.txt (np. po aktualizacji)
fc /b requirements.txt ".venv\zainstalowane.txt" >nul 2>&1
if not errorlevel 1 goto run

echo Instaluje biblioteki (pyserial, vgamepad, pyvjoy, esptool)...
echo Jesli pojawi sie instalator sterownika ViGEmBus - zaakceptuj go.
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [BLAD] Instalacja bibliotek nie powiodla sie. Sprawdz internet i sprobuj ponownie.
    pause
    exit /b 1
)
copy /y requirements.txt ".venv\zainstalowane.txt" >nul

:run
"%VENV_PY%" kierownica.py %*

echo.
echo Program zakonczony.
pause
