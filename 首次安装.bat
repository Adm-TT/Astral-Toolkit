@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
rem OCR needs Python 3.10-3.13 (onnxruntime has no wheels for newer versions yet).
rem Find one, or install Python 3.12, then build a private .venv here.
rem Never read Python's path back through cmd: if the Windows user name has Chinese characters the path
rem gets garbled (UTF-8 vs GBK) and every later step fails with "path not found". Use the py launcher instead.
set PYEXE=
for %%v in (3.12 3.13 3.11 3.10) do (
  if not defined PYEXE (
    py -%%v -c "import sys" >nul 2>&1 && set "PYEXE=py -%%v"
  )
)
if defined PYEXE goto havepy

rem In mainland China python.org / winget are very slow: use a domestic mirror of the official installer there.
set "CN="
for /f "delims=" %%z in ('tzutil /g') do if /i "%%z"=="China Standard Time" set "CN=1"
if defined CN goto mirror
echo No compatible Python found. Installing Python 3.12 with winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
call :findpy
if defined PYEXE goto havepy

:mirror
echo Downloading Python 3.12 from a mirror (about 26 MB)...
set "PYSETUP=%TEMP%\python-3.12.10-amd64.exe"
curl -L --retry 3 -o "%PYSETUP%" https://registry.npmmirror.com/-/binary/python/3.12.10/python-3.12.10-amd64.exe
if errorlevel 1 curl -L --retry 3 -o "%PYSETUP%" https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-amd64.exe
rem Only run it if it really is the official installer signed by the Python Software Foundation.
powershell -NoProfile -Command "$s=Get-AuthenticodeSignature '%PYSETUP%'; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Python Software Foundation'){exit 1}"
if errorlevel 1 (
  echo The downloaded installer failed the signature check, not running it.
  del "%PYSETUP%" 2>nul
  goto nopy
)
echo Installing Python 3.12...
"%PYSETUP%" /quiet InstallAllUsers=0 Include_launcher=1 PrependPath=0 Include_test=0
del "%PYSETUP%" 2>nul
call :findpy
if defined PYEXE goto havepy

:nopy
echo Could not set up Python 3.12 automatically.
echo Please install it from https://www.python.org/downloads/release/python-31210/
echo then run this file again.
pause
exit /b

:findpy
py -3.12 -c "import sys" >nul 2>&1 && set "PYEXE=py -3.12" && exit /b
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYEXE="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%ProgramFiles%\Python312\python.exe" set PYEXE="%ProgramFiles%\Python312\python.exe"
exit /b

:havepy
echo Using %PYEXE%
rem A half-made .venv from an earlier failed run: remove it and start again
if exist ".venv" if not exist ".venv\Scripts\python.exe" rmdir /s /q ".venv"
if not exist ".venv\Scripts\python.exe" %PYEXE% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo Could not create the Python environment in this folder.
  echo Try extracting this folder to a simple place like C:\Dubhe and run this file again.
  pause
  exit /b
)
".venv\Scripts\python.exe" -m sc_mining.run install
pause
