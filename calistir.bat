@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".kurulum_tamam" (
  echo Ilk calistirma: gerekli kutuphaneler kuruluyor...
  %PY% -m pip install -r requirements.txt || (echo Python bulunamadi. python.org adresinden kurup tekrar dene. & pause & exit /b 1)
  echo ok> .kurulum_tamam
)
%PY% takip.py
if "%1"=="sessiz" exit /b 0
start "" "docs\index.html"
