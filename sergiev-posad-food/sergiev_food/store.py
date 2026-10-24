"""Хранилище: один JSON-файл со словарём {id организации: запись}."""
import json
import os


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, places):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(places, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)  # атомарно: прерывание не портит файл
