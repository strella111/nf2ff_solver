@echo off
REM ==========================================================================
REM  Сборка FarZone в один исполняемый файл (Windows, PyInstaller)
REM  Результат: dist\FarZone.exe
REM ==========================================================================
setlocal

echo [1/2] Установка зависимостей...
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [2/2] Сборка PyInstaller...
pyinstaller --noconfirm --clean FarZone.spec
if errorlevel 1 goto :error

echo.
echo === Готово: dist\FarZone.exe ===
goto :eof

:error
echo.
echo *** ОШИБКА сборки ***
exit /b 1
