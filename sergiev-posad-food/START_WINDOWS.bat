@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Сергиев Посад: рейтинг заведений общепита (без API-ключей)
echo ============================================================
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python не найден. Установите его с https://www.python.org/downloads/
  echo и ОБЯЗАТЕЛЬНО поставьте галочку "Add python.exe to PATH" на первом экране установки.
  echo Потом запустите этот файл снова.
  pause
  exit /b 1
)
if not exist .venv (
  echo Первый запуск: готовлю окружение, это займёт несколько минут...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q playwright
python -m playwright install chromium
echo.
echo Сейчас откроется окно браузера. Не закрывайте его и не трогайте мышью.
echo Если появится капча, решите её в окне браузера и нажмите Enter в этом чёрном окне.
echo Остановить: Ctrl+C. Потом можно запустить снова — продолжит с того же места.
echo.
python -m sergiev_food browse
echo.
if exist data\ranking.csv start "" data
pause
