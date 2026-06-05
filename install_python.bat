@echo off
REM ========================================================================
REM  install_python.bat  -  Installerer Python 3.12 automatisk paa Windows
REM
REM  Kores hvis du kun vil have Python installeret (uden at bygge .exe'en).
REM  build_windows.bat kalder denne fil automatisk hvis Python mangler.
REM ========================================================================

setlocal
cd /d "%~dp0"

echo.
echo === Installerer Python 3.12 ===
echo.

REM ---- Forsoeg 1: winget (findes paa de fleste Windows 10/11) -------------
where winget >nul 2>&1
if not errorlevel 1 (
    echo Bruger winget...
    winget install --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements --scope user
    if not errorlevel 1 goto :success
    echo winget fejlede - proever direkte download i stedet...
    echo.
)

REM ---- Forsoeg 2: download installer fra python.org -----------------------
set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
set "PY_INSTALLER=%TEMP%\python-3.12.7-amd64.exe"

echo Henter Python installer (ca. 27 MB) fra python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo.
    echo FEJL: Kunne ikke hente Python installer.
    echo Tjek din internetforbindelse, eller installer manuelt:
    echo   https://python.org/downloads/
    pause
    exit /b 1
)
if not exist "%PY_INSTALLER%" (
    echo FEJL: Installer-fil ikke fundet efter download.
    pause
    exit /b 1
)

echo.
echo Installerer Python (tager ca. 1 minut, stille og roligt)...
echo - Tilfoejer Python til PATH
echo - Installerer kun for denne bruger (kraever ikke admin)
echo.
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
if errorlevel 1 (
    echo Installation fejlede med fejlkode %errorlevel%.
    echo Proev at koere installeren manuelt: %PY_INSTALLER%
    pause
    exit /b 1
)

del "%PY_INSTALLER%" >nul 2>&1

:success
echo.
echo ========================================================================
echo  Python er installeret!
echo.
echo  VIGTIGT: Luk dette vindue og aabn et NYT for at Windows kan se Python.
echo  Derefter kan du koere build_windows.bat
echo ========================================================================
echo.
pause
exit /b 0
