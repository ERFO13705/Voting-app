"""Дообогащение: рейтинг, число оценок/отзывов и статус (работает/закрыто) со страницы организации.

Яндекс кладёт состояние страницы в <script class="state-view"> как JSON. Структура
не документирована и может меняться, поэтому поиск полей устойчивый (рекурсивный),
а при сбое разбора сырой HTML можно сохранить (--dump-dir) для диагностики.
Страницы защищены SmartCaptcha: при её появлении сбор останавливается, прогресс сохраняется.
"""
import json
import random
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
STATE_RE = re.compile(r'<script[^>]*class="state-view"[^>]*>(.*?)</script>', re.S)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
PERMANENT_MARKERS = ("закрыто навсегда", "закрыта навсегда", "больше не работает",
                     "организация ликвидирована", "организация закрыта")
TEMPORARY_MARKERS = ("временно закрыто", "временно закрыта", "временно не работает")
CAPTCHA_MARKERS = ("showcaptcha", "smartcaptcha", "вы не робот", "captcha-page")

# статусы: open | temporarily_closed | permanently_closed | removed | unknown


class CaptchaError(RuntimeError):
    pass


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            yield n
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)


def _num(value, cast):
    try:
        return cast(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _has(text, markers):
    text = text.lower()
    return any(m in text for m in markers)


def parse_org_page(html, org_id):
    """-> {rating, rating_count, review_count, status, title, match}."""
    title_m = TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    out = {"rating": None, "rating_count": None, "review_count": None,
           "status": "unknown", "title": title, "match": "none"}

    state_m = STATE_RE.search(html)
    if not state_m:
        return out
    try:
        state = json.loads(state_m.group(1))
    except ValueError:
        return out

    # В state есть и соседние организации; берём блок, чей id совпадает с нужным.
    exact = loose = None
    for d in _walk(state):
        if "ratingData" in d or "ratingValue" in d:
            ident = str(d.get("id") or d.get("permalink") or "")
            if ident == org_id:
                exact = d
                break
            loose = loose or d
    block = exact or loose
    if block is None:
        # рейтинга нет (новое заведение) — статус всё равно определим по заголовку
        out["status"] = _status_from(title, None)
        return out
    out["match"] = "exact" if exact else "loose"

    rd = block.get("ratingData") if isinstance(block.get("ratingData"), dict) else block
    out["rating"] = _num(rd.get("ratingValue"), float)
    out["rating_count"] = _num(rd.get("ratingCount"), int)
    out["review_count"] = _num(rd.get("reviewCount"), int)
    out["status"] = _status_from(title, block)
    return out


def _status_from(title, block):
    blob = title
    if block is not None:
        blob += " " + json.dumps(block, ensure_ascii=False)
        for k, v in block.items():
            if v and k.lower().replace("_", "") in ("permanentclosed", "permanentlyclosed"):
                return "permanently_closed"
    if _has(blob, PERMANENT_MARKERS):
        return "permanently_closed"
    if _has(blob, TEMPORARY_MARKERS):
        return "temporarily_closed"
    return "open"


def fetch_org_page(org_id, timeout=30):
    url = f"https://yandex.ru/maps/org/{org_id}/"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url, body = resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # страницы нет — организация удалена
        if e.code in (403, 429):
            raise CaptchaError(f"HTTP {e.code}")
        raise
    if _has(final_url, CAPTCHA_MARKERS) or _has(body[:5000], CAPTCHA_MARKERS):
        raise CaptchaError("SmartCaptcha")
    return body


def enrich(places, delay=5.0, limit=None, force=False, dump_dir=None, log=print,
           fetch=fetch_org_page, save=None, sleep=time.sleep):
    """Дополняет записи in-place. save() вызывается после каждой организации."""
    todo = [p for p in places.values() if force or not p.get("enriched_at")]
    if limit:
        todo = todo[:limit]
    for i, place in enumerate(todo, 1):
        try:
            html = fetch(place["id"])
        except CaptchaError as e:
            log(f"[enrich] остановка: {e}. Прогресс сохранён, повторите запуск позже "
                f"(или с другого IP/через паузу).")
            return False
        if html is None:
            place.update(status="removed", rating=None, rating_count=None, review_count=None)
        else:
            info = parse_org_page(html, place["id"])
            if info["match"] == "none" and dump_dir:
                _dump(dump_dir, place["id"], html)
            if not place.get("name") and info["title"]:
                place["name"] = info["title"].split(",")[0]
            place.update({k: info[k] for k in ("rating", "rating_count", "review_count", "status")})
            place["parse_match"] = info["match"]
        place["enriched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if save:
            save()
        log(f"[enrich] {i}/{len(todo)} {place['name'] or place['id']}: "
            f"{place['status']} {place.get('rating')} ({place.get('rating_count')})")
        sleep(delay * random.uniform(0.7, 1.4))
    return True


def _dump(dump_dir, org_id, html):
    import os
    os.makedirs(dump_dir, exist_ok=True)
    with open(os.path.join(dump_dir, f"{org_id}.html"), "w", encoding="utf-8") as f:
        f.write(html)
