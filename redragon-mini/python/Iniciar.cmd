@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 configure.py %*
  goto fim
)
where python >nul 2>&1
if not errorlevel 1 (
  python configure.py %*
  goto fim
)
echo Python nao encontrado. Instale o Python 3.10 ou superior para Windows.
echo Download oficial: https://www.python.org/downloads/windows/
echo Depois abra este arquivo novamente. Nao precisa instalar pacotes pip.
:fim
echo.
pause
