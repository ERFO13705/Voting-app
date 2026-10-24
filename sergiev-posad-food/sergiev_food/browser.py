"""Режим «без ключей»: настоящий браузер (Playwright), открытый окном, медленно и по одной странице.

Сначала проходит поиск по категориям (прокручивает список результатов и собирает ссылки на
организации), потом открывает карточки. Если Яндекс покажет капчу — программа подаёт звуковой
сигнал и ждёт, пока человек решит её в окне браузера; после этого продолжает сама. Капчу
программа не решает и не обходит. После каждой капчи темп замедляется.
"""
import os
import random
import re
import sys
import time
from urllib.parse import quote

from .discover import QUERIES
from .enrich import CAPTCHA_MARKERS, CaptchaError, FetchError, _has

SEARCH_URL = ("https://yandex.ru/maps/?ll=38.135969%2C56.315313&mode=search"
              "&text={q}&z=13")
ORG_URL = "https://yandex.ru/maps/org/{id}/"
ORG_PATH_RE = re.compile(r"/org/(?:[^/?#\s]+/)?(\d{5,})")
CAPTCHA_TEXT = ("вы не робот", "подтвердите, что запросы", "введите символы", "я не робот")
MAX_SLOWDOWN = 4.0


def beep():
    try:
        import winsound
        winsound.Beep(1000, 400)
        winsound.Beep(1400, 400)
    except Exception:
        sys.stdout.write("\a")
        sys.stdout.flush()


class YandexBrowser:
    def __init__(self, profile_dir, headless=False, log=print, notify=beep,
                 search_url=None, org_url=None, sleep=time.sleep, launch_kwargs=None,
                 captcha_timeout=1800, retries=3, debug_dir=None):
        self.profile_dir, self.headless, self.log, self.notify = profile_dir, headless, log, notify
        self.search_url, self.org_url, self.sleep = search_url or SEARCH_URL, org_url or ORG_URL, sleep
        self.launch_kwargs = launch_kwargs or {}
        self.captcha_timeout, self.retries, self.debug_dir = captcha_timeout, retries, debug_dir
        self.slowdown = 1.0     # растёт после каждой капчи
        self.captchas = 0

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
        self.sleep(random.uniform(lo, hi) * self.slowdown)

    def _is_captcha(self):
        if _has(self.page.url, CAPTCHA_MARKERS):
            return True
        try:
            text = self.page.inner_text("body", timeout=5000)[:1500]
        except Exception:
            return False
        return _has(text, CAPTCHA_TEXT)

    def _wait_captcha(self):
        """Если открыта капча — зовёт человека и ждёт, пока он её решит (без нажатия Enter)."""
        if not self._is_captcha():
            return
        self.captchas += 1
        if self.headless:
            raise CaptchaError("капча в режиме без окна — запустите без --headless")
        self.slowdown = min(self.slowdown * 1.5, MAX_SLOWDOWN)
        self.log("\n>>> Яндекс просит пройти проверку (капчу). Решите её в окне браузера —\n"
                 ">>> программа продолжит сама, как только капча исчезнет. Темп будет замедлен.")
        waited = 0
        while self._is_captcha():
            if waited % 30 == 0:
                self.notify()  # повторный сигнал каждые 30 секунд
            if waited >= self.captcha_timeout:
                raise CaptchaError("капча не решена за %d мин" % (self.captcha_timeout // 60))
            self.sleep(2)
            waited += 2
        self._pause(3, 6)

    def _goto(self, url):
        """Переход с повторами при сетевых сбоях/таймаутах; -> HTTP-код ответа."""
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                return resp.status if resp is not None else None
            except Exception as e:  # playwright.Error / TimeoutError
                last = e
                self.log(f"[браузер] сбой загрузки (попытка {attempt}/{self.retries}): {str(e).splitlines()[0][:100]}")
                self.sleep(5 * attempt)
        raise FetchError(str(last).splitlines()[0][:100])

    def _hrefs(self):
        hrefs = self.page.eval_on_selector_all('a[href*="/org/"]', "els => els.map(e => e.href)")
        return {m for h in hrefs for m in ORG_PATH_RE.findall(h)}

    def _snapshot(self, name):
        if not self.debug_dir:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        try:
            self.page.screenshot(path=os.path.join(self.debug_dir, name + ".png"))
            with open(os.path.join(self.debug_dir, name + ".html"), "w", encoding="utf-8") as f:
                f.write(self.page.content())
        except Exception:
            pass

    def search(self, query, max_rounds=80):
        """-> множество ID организаций из выдачи по запросу."""
        self._goto(self.search_url.format(q=quote(query + " Сергиев Посад")))
        self._pause(4, 7)
        self._wait_captcha()
        ids, stale = set(), 0
        self.page.mouse.move(200, 500)  # курсор над списком слева — иначе колесо крутит карту
        for _ in range(max_rounds):
            self.page.mouse.wheel(0, 2500)
            self._pause(1.5, 3)
            if self._is_captcha():
                self._wait_captcha()
            found = self._hrefs()
            stale = stale + 1 if found <= ids else 0
            ids |= found
            if stale >= 4:
                break
        if not ids:
            self._snapshot("search_empty_" + re.sub(r"\W+", "_", query))
        return ids

    def fetch_org(self, org_id):
        """HTML карточки; None — если страницы нет. Капчу решает человек."""
        status = self._goto(self.org_url.format(id=org_id))
        if status == 404:
            return None
        self._pause(3, 5)
        self._wait_captcha()
        return self.page.content()


def browse_discover(browser, places, done, save, log=print, pause=(6, 12), max_empty=3):
    """Проходит по QUERIES; done — уже пройденные запросы (список), save() сохраняет прогресс.

    Прекращает работу, если первые max_empty запросов подряд ничего не дали (скорее всего,
    изменилась вёрстка или блокировка) — иначе пришлось бы ждать час впустую.
    """
    empty, found_any = 0, False
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
        if ids:
            done.append(query)  # пустой запрос не помечаем выполненным — повторится в следующий раз
            empty, found_any = 0, True
        else:
            empty += 1
        save()
        log(f"[поиск] «{query}»: найдено {len(ids)}, новых {added}, всего {len(places)}")
        if empty >= max_empty and not found_any:
            log("[поиск] ОСТАНОВКА: несколько запросов подряд без результатов. Проверьте окно браузера "
                "(капча? пустая карта?) и запустите с --dump-dir debug, пришлите папку debug.")
            return False
        browser._pause(*pause)
    return True
