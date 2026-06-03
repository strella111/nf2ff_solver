@echo off
REM ==========================================================================
REM  Сборка FarZone в один исполняемый файл (Windows, PyInstaller)
REM  Вся работа идёт в изолированном venv (.venv) — глобальный Python не трогается.
REM  Результат: dist\FarZone.exe
REM ==========================================================================
setlocal

python build.py %*
if errorlevel 1 goto :error

goto :eof

:error
echo.
echo *** ОШИБКА сборки ***
exit /b 1
