@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Bilgisayar acikken her 30 dakikada bir takibi arka planda (pencere acmadan) calistirir.
call calistir.bat sessiz
where pyw >nul 2>nul
if %errorlevel%==0 (
  schtasks /Create /F /SC MINUTE /MO 30 /TN "TakipAkisi" /TR "pyw -3 \"%~dp0takip.py\""
) else (
  schtasks /Create /F /SC MINUTE /MO 30 /TN "TakipAkisi" /TR "cmd /c \"%~dp0calistir.bat\" sessiz"
)
if errorlevel 1 (echo Gorev olusturulamadi. & pause & exit /b 1)
echo.
echo Tamam: "TakipAkisi" gorevi her 30 dakikada bir calisacak.
echo Akis sayfan: %~dp0docs\index.html
echo Kaldirmak icin: schtasks /Delete /TN "TakipAkisi" /F
pause
