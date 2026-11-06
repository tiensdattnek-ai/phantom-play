@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title PhantomPlay Remote Play
color 0B

echo ============================================================
echo   PhantomPlay - Remote play trong trinh duyet
echo   Windows launcher: cai dat + Cloudflare Quick Tunnel
echo ============================================================
echo.

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3"
)
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    echo [!] Khong tim thay Python 3.10+. Dang thu cai bang winget...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo [!] Hay cai Python 3.12 tu https://www.python.org/downloads/ roi chay lai start.bat
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        set "PY_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
    ) else if exist "%ProgramFiles%\Python312\python.exe" (
        set "PY_CMD=%ProgramFiles%\Python312\python.exe"
    ) else (
        set "PY_CMD=py -3"
    )
)

echo [*] Python: %PY_CMD%
if not exist ".venv\Scripts\python.exe" (
    echo [*] Tao virtual environment...
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :fail
)
call ".venv\Scripts\activate.bat"

echo [*] Cai Python dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [*] Cai gamepad ao (tuy chon, co the hoi UAC/ViGEmBus)...
python -m pip install -r requirements-gamepad.txt
if errorlevel 1 echo [!] Khong cai duoc vgamepad. Van choi duoc bang gamepad-to-keyboard.

echo [*] Tai FFmpeg + cloudflared vao runtime/bin...
python scripts\bootstrap.py
if errorlevel 1 goto :fail

echo.
echo [*] Khoi dong PhantomPlay. Neu la lan dau, nhap mat khau hoac Enter de tu tao.
echo [*] Gamepad ao tren Windows co the yeu cau ViGEmBus/UAC. Neu khong cai driver,
echo     client van co the dung che do gamepad-to-keyboard.
echo.
python -m phantom %*
if errorlevel 1 goto :fail
pause
exit /b 0

:fail
echo.
echo [!] Co loi xay ra. Xem thong bao phia tren.
pause
exit /b 1
