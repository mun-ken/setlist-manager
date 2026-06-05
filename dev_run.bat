@echo off
REM =====================================================================
REM  dev_run.bat - Koer Setlist Manager direkte fra kildekoden
REM
REM  Brug denne mens du AENDRER i koden - den starter programmet paa
REM  ca. 2 sekunder, i stedet for at vente paa et helt PyInstaller-build.
REM
REM  Foerste gang: koerer build_windows.bat foerst saa .venv er klar.
REM =====================================================================

setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Foerste gang - opretter miljoe...
    call build_windows.bat
    if errorlevel 1 exit /b 1
    echo.
    echo === Klar! Naeste gang gaar det meget hurtigere. ===
    echo.
)

call .venv\Scripts\activate.bat
python main.py

endlocal
