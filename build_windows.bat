@echo off
REM =====================================================================
REM  Setlist Manager - One-click Windows build
REM  Builds dist\SetlistManager\ (onedir distribution med alle DLL'er).
REM
REM  Hvis Python ikke er installeret, tilbyder scriptet at installere
REM  det automatisk - du behoever ikke gore noget selv.
REM =====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo === [1/5] Leder efter Python ===

set "PYEXE="

REM ---- Try 1: 'python' on PATH ----------------------------------------
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=python"
        goto :have_python
    )
)

REM ---- Try 2: 'py' launcher -------------------------------------------
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=py -3"
        goto :have_python
    )
)

REM ---- Try 3: scan common install locations ---------------------------
call :scan_paths
if defined PYEXE goto :have_python

REM ---- Python not found - offer to install it -------------------------
echo.
echo Python er ikke installeret paa denne computer.
echo.
echo Setlist Manager skal bruge Python for at blive bygget.
echo Vi kan installere det automatisk (helt gratis, fra python.org).
echo.
choice /C JN /N /M "Vil du installere Python automatisk nu? (J=Ja, N=Nej): "
if errorlevel 2 goto :manual_help

echo.
call install_python.bat
if errorlevel 1 (
    echo.
    echo Python kunne ikke installeres automatisk.
    goto :manual_help
)

REM After install, the new PATH isn't visible in the current cmd session.
REM Re-scan the install locations directly.
call :scan_paths
if defined PYEXE goto :have_python

REM Last resort: try py launcher (should always work after fresh install)
where py >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3"
    goto :have_python
)

echo.
echo Python blev installeret men kan ikke ses i dette vindue endnu.
echo.
echo  ====^>  Luk dette vindue og dobbeltklik build_windows.bat igen.
echo.
pause
exit /b 0

:manual_help
echo.
echo ============================================================
echo  Manuel installation:
echo  1. Aabn https://python.org/downloads/ i din browser
echo  2. Download "Python 3.12" (knappen oeverst)
echo  3. Koer installeren - SAET FLUEBEN i "Add Python to PATH"
echo  4. Dobbeltklik build_windows.bat igen
echo ============================================================
echo.
pause
exit /b 1

:have_python
echo Python fundet: %PYEXE%
%PYEXE% --version
echo.

echo === [2/5] Opretter virtuelt miljoe (.venv) ===
if not exist .venv (
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo FEJL: Kunne ikke oprette virtuelt miljoe.
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

echo.
echo === [3/5] Installerer build-afhaengigheder ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo FEJL: Kunne ikke installere afhaengigheder.
    pause
    exit /b 1
)

echo.
echo === [4/5] Genererer app-ikon ===
python make_icon.py

echo.
echo === [5/5] Bygger SetlistManager.exe med PyInstaller ===
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
pyinstaller setlist.spec --noconfirm
if errorlevel 1 (
    echo BUILD FEJLEDE - se fejlbeskeden ovenfor.
    pause
    exit /b 1
)

echo.
if exist dist\SetlistManager\SetlistManager.exe (
    REM Hent version fra version.py for at vise den i output
    for /f "delims=" %%V in ('python -c "from version import APP_VERSION; print(APP_VERSION)"') do set "APP_VERSION=%%V"

    echo ============================================================
    echo  BUILD OK!  Version: %APP_VERSION%
    echo  Mappe: %cd%\dist\SetlistManager\
    echo  EXE:   %cd%\dist\SetlistManager\SetlistManager.exe
    echo.
    echo  Du kan koere SetlistManager.exe direkte (dobbeltklik den i
    echo  mappen ovenfor — den HELE mappe skal flyttes sammen, ikke
    echo  bare den ene .exe-fil!).
    echo.
    echo  For at lave en rigtig installer-fil (anbefales!):
    echo    1. Installer Inno Setup 6 fra https://jrsoftware.org/isinfo.php
    echo    2. Hojreklik installer.iss -^> "Compile"
    echo       (versionen bliver automatisk taget fra APP_VERSION env-var)
    echo    3. Find SetlistManagerSetup.exe i Output\ mappen
    echo ============================================================
) else (
    echo BUILD FEJLEDE - dist\SetlistManager\SetlistManager.exe blev ikke oprettet.
    exit /b 1
)

endlocal
pause
exit /b 0


REM =====================================================================
REM  Subroutine: scan common Python install locations
REM  Sets PYEXE if found.
REM =====================================================================
:scan_paths
for %%V in (313 312 311 310 309 308) do (
    if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    )
    if not defined PYEXE if exist "C:\Python%%V\python.exe" (
        set "PYEXE=C:\Python%%V\python.exe"
    )
    if not defined PYEXE if exist "C:\Program Files\Python%%V\python.exe" (
        set "PYEXE=C:\Program Files\Python%%V\python.exe"
    )
    if not defined PYEXE if exist "C:\Program Files (x86)\Python%%V\python.exe" (
        set "PYEXE=C:\Program Files (x86)\Python%%V\python.exe"
    )
)
exit /b 0

