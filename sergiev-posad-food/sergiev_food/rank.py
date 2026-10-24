"""Ранжирование: сначала работающие, внутри группы — по байесовскому рейтингу.

Сырая средняя оценка нечестна: 5.0 по 2 отзывам не лучше 4.7 по 800. Поэтому
score = v/(v+m)*R + m/(v+m)*C, где R — рейтинг, v — число оценок, C — средний
рейтинг по городу, m — «вес сомнения» (сколько оценок нужно, чтобы доверять заведению).
"""
import csv

STATUS_GROUP = {"open": 0, "unknown": 1, "temporarily_closed": 2,
                "permanently_closed": 3, "removed": 3}
STATUS_RU = {"open": "работает", "unknown": "статус неизвестен",
             "temporarily_closed": "временно закрыто",
             "permanently_closed": "закрыто навсегда", "removed": "удалено/ликвидировано"}


def votes(p):
    return p.get("rating_count") or p.get("review_count") or 0


def rank(places, m=10):
    items = [dict(p) for p in places.values()]
    rated = [p for p in items if p.get("rating")]
    c = sum(p["rating"] for p in rated) / len(rated) if rated else 0.0
    for p in items:
        v = votes(p)
        p["score"] = round((v / (v + m)) * p["rating"] + (m / (v + m)) * c, 3) if p.get("rating") else None
    items.sort(key=lambda p: (
        STATUS_GROUP.get(p.get("status", "unknown"), 1),
        p["score"] is None,           # без рейтинга — в конец своей группы
        -(p["score"] or 0),
        -votes(p),
        p.get("name", ""),
    ))
    for i, p in enumerate(items, 1):
        p["rank"] = i
    return items


COLUMNS = [("rank", "№"), ("name", "Название"), ("status_ru", "Статус"), ("rating", "Рейтинг"),
           ("rating_count", "Оценок"), ("review_count", "Отзывов"), ("score", "Взвеш. балл"),
           ("categories_s", "Категории"), ("address", "Адрес"), ("phones_s", "Телефон"),
           ("hours", "Часы"), ("url", "Яндекс Карты")]


def _rows(items):
    for p in items:
        yield {**p,
               "status_ru": STATUS_RU.get(p.get("status", "unknown"), p.get("status", "")),
               "categories_s": ", ".join(p.get("categories", [])),
               "phones_s": ", ".join(p.get("phones", []))}


def write_csv(items, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM — чтобы Excel понял кириллицу
        w = csv.writer(f, delimiter=";")
        w.writerow([h for _, h in COLUMNS])
        for r in _rows(items):
            w.writerow(["" if r.get(k) is None else r.get(k) for k, _ in COLUMNS])


def write_markdown(items, path):
    cols = [c for c in COLUMNS if c[0] in
            ("rank", "name", "status_ru", "rating", "rating_count", "review_count", "score", "address")]
    with open(path, "w", encoding="utf-8") as f:
        f.write("| " + " | ".join(h for _, h in cols) + " |\n")
        f.write("|" + "---|" * len(cols) + "\n")
        for r in _rows(items):
            cells = []
            for k, _ in cols:
                v = r.get(k)
                v = "" if v is None else str(v).replace("|", "/")
                cells.append(f"[{v}]({r['url']})" if k == "name" else v)
            f.write("| " + " | ".join(cells) + " |\n")
