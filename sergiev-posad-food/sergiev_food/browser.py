"""Режим «без ключей»: настоящий браузер (Playwright), открытый окном, медленно и по одной странице.

Сначала проходит поиск по категориям (прокручивает список результатов и собирает ссылки на
организации), потом открывает карточки. Если Яндекс покажет капчу — решите её в окне
браузера и нажмите Enter в консоли.
"""
import os
import random
import re
import time
from urllib.parse import quote

from .discover import QUERIES
from .enrich import CAPTCHA_MARKERS, _has

SEARCH_URL = ("https://yandex.ru/maps/?ll=38.135969%2C56.315313&mode=search"
              "&text={q}&z=13")
ORG_URL = "https://yandex.ru/maps/org/{id}/"
ORG_PATH_RE = re.compile(r"/org/(?:[^/?#\s]+/)?(\d{5,})")


class YandexBrowser:
    def __init__(self, profile_dir, headless=False, log=print, ask=input,
                 search_url=SEARCH_URL, org_url=ORG_URL, sleep=time.sleep, launch_kwargs=None):
        self.profile_dir, self.headless, self.log, self.ask = profile_dir, headless, log, ask
        self.search_url, self.org_url, self.sleep = search_url, org_url, sleep
        self.launch_kwargs = launch_kwargs or {}

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SystemExit("Не установлен Playwright. Запустите START_WINDOWS.bat "
                             "(или: pip install playwright && python -m playwright install chromium)")
        os.makedirs(self.profile_dir, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            self.profile_dir, headless=self.headless, locale="ru-RU",
            viewport={"width": 1300, "height": 900}, **self.launch_kwargs)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc):
        self.ctx.close()
        self._pw.stop()

    def _pause(self, lo, hi):
        self.sleep(random.uniform(lo, hi))

    def _is_captcha(self):
        page = self.page
        if _has(page.url, CAPTCHA_MARKERS):
            return True
        try:
            text = page.inner_text("body", timeout=5000)[:1500]
        except Exception:
            return False
        return _has(text, ("вы не робот", "подтвердите, что запросы", "введите символы"))

    def _wait_captcha(self):
        while self._is_captcha():
            self.log("\n>>> Яндекс просит пройти проверку (капчу). Решите её в окне браузера,\n"
                     ">>> дождитесь, пока откроется карта, и нажмите Enter здесь.")
            self.ask("")
            self._pause(2, 4)

    def _hrefs(self):
        hrefs = self.page.eval_on_selector_all('a[href*="/org/"]', "els => els.map(e => e.href)")
        return {m for h in hrefs for m in ORG_PATH_RE.findall(h)}

    def search(self, query, max_rounds=80):
        """-> множество ID организаций из выдачи по запросу."""
        self.page.goto(self.search_url.format(q=quote(query + " Сергиев Посад")),
                       wait_until="domcontentloaded")
        self._pause(4, 7)
        self._wait_captcha()
        ids, stale = set(), 0
        self.page.mouse.move(200, 500)  # курсор над списком слева — иначе колесо крутит карту
        for _ in range(max_rounds):
            self.page.mouse.wheel(0, 2500)
            self._pause(1.5, 3)
            found = self._hrefs()
            stale = stale + 1 if found <= ids else 0
            ids |= found
            if stale >= 4:
                break
        return ids

    def fetch_org(self, org_id):
        """HTML карточки; None — если страницы нет. Капчу обрабатывает человек."""
        resp = self.page.goto(self.org_url.format(id=org_id), wait_until="domcontentloaded")
        if resp is not None and resp.status == 404:
            return None
        self._pause(3, 5)
        self._wait_captcha()
        return self.page.content()


def browse_discover(browser, places, done, save, log=print, pause=(6, 12)):
    """Проходит по QUERIES; done — уже пройденные запросы (список), save() сохраняет прогресс."""
    for query in QUERIES:
        if query in done:
            continue
        ids = browser.search(query)
        added = 0
        for oid in ids:
            if oid not in places:
                places[oid] = {"id": oid, "name": "", "address": "", "lat": None, "lon": None,
                               "categories": [], "phones": [], "website": "", "hours": "",
                               "url": f"https://yandex.ru/maps/org/{oid}/"}
                added += 1
        done.append(query)
        save()
        log(f"[поиск] «{query}»: найдено {len(ids)}, новых {added}, всего {len(places)}")
        browser._pause(*pause)
    return places
