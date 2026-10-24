#!/bin/bash
cd "$(dirname "$0")"
echo "Сергиев Посад: рейтинг заведений общепита (без API-ключей)"
if ! command -v python3 >/dev/null; then
  echo "Python 3 не найден. Установите с https://www.python.org/downloads/ и запустите снова."
  read -p "Enter для выхода"; exit 1
fi
[ -d .venv ] || { echo "Первый запуск: готовлю окружение..."; python3 -m venv .venv; }
source .venv/bin/activate
pip install -q playwright
python -m playwright install chromium
echo "Сейчас откроется окно браузера. Если появится капча — решите её там и нажмите Enter здесь."
echo "Быстрая самопроверка (1-2 минуты)..."
if ! python -m sergiev_food check; then
  echo "Самопроверка не прошла. Пришлите мне текст из этого окна и папку data/debug."
  read -p "Продолжить полный прогон всё равно? [y/N] " a; [ "$a" = "y" ] || exit 1
fi
python -m sergiev_food browse
[ -f data/ranking.csv ] && { command -v open >/dev/null && open data || true; }
read -p "Готово. Enter для выхода"
