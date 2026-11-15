@echo off
REM ==========================================================
REM  GT Wheel - configurator and background program (icon next to the clock)
REM  On the first run it creates a Python environment
REM  (folder pc\.venv) and installs the required libraries.
REM  Close GT_Wheel.bat before starting (only one program can
REM  hold the COM port). Parameters, e.g.:
REM     GT_Wheel_Configurator.bat --port COM5
REM ==========================================================
setlocal
title GT Wheel - configurator
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
REM The libraries are reinstalled when requirements.txt changes (e.g. after an update)
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
REM The program runs in the background (icon next to the clock), so it starts without a console window.
REM Messages go to pc\kierownica_gt.log.
set "VENV_PYW=.venv\Scripts\pythonw.exe"
if not exist "%VENV_PYW%" set "VENV_PYW=%VENV_PY%"
start "" "%VENV_PYW%" konfigurator.py %*
exit /b 0
