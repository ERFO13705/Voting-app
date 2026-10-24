"""Сквозной тест режима browse против локального мок-сервера (нужны playwright и chromium)."""
import csv
import glob
import json
import os
import sys
import tempfile
import threading
import unittest
import http.server

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import playwright  # noqa: F401
    CHROME = (glob.glob(os.environ.get("SERGIEV_TEST_CHROMIUM", "") or "/nonexistent")
              or glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
except ImportError:
    CHROME = []

BASE = 1000000
PORT = 8791
CAPTCHA_ID, FLAKY_ID, GONE_ID, OUTSIDE_ID, NOJSON_ID = 5, 6, 11, 3, 8


class Mock(http.server.BaseHTTPRequestHandler):
    captcha_solved = False
    flaky_on = True
    captcha_shown = 0

    def log_message(self, *a):
        pass

    def _send(self, body, status=200):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/empty":
            return self._send("<html><body>ничего нет</body></html>")
        if path == "/search":
            links = "".join(f'<a href="/maps/org/cafe_{i}/{BASE + i}/">c{i}</a><br>' for i in range(1, 31))
            return self._send(f"<html><body style='height:6000px'>{links}</body></html>")
        if path == "/favicon.ico":
            return self._send("", 404)
        i = int(path.rstrip("/").split("/")[-1]) - BASE
        if i == CAPTCHA_ID and not Mock.captcha_solved:
            Mock.captcha_shown += 1
            return self._send("<html><head><title>Яндекс</title><meta http-equiv='refresh' content='1'></head>"
                              "<body>Вы не робот? Подтвердите, "
                              "что запросы отправляли вы</body></html>")
        if i == FLAKY_ID and Mock.flaky_on:
            self.connection.close()
            return
        if i == GONE_ID:
            return self._send("not found", 404)
        city = "Хотьково" if i == OUTSIDE_ID else "Сергиев Посад"
        title = f"Кафе {i}, кафе, ул. Тест, {i}, {city} — Яндекс Карты"
        if i == NOJSON_ID:
            return self._send(f"<html><head><title>{title}</title></head><body><div>4,4</div>"
                              f"<div>77 оценок</div></body></html>")
        neighbour = {"id": "42424242", "title": "Сосед", "ratingData": {"ratingValue": 1.1, "ratingCount": 9999, "reviewCount": 1}}
        me = {"id": str(BASE + i), "title": f"Кафе {i}",
              "ratingData": {"ratingValue": 3.0 + (i % 20) / 10, "ratingCount": 50 + i, "reviewCount": 5}}
        if i % 7 == 0:
            me["closedNote"] = "Закрыто навсегда"
        state = {"results": [neighbour, me]}  # сосед стоит ПЕРЕД нужной организацией
        self._send(f"<html><head><title>{title}</title></head><body>"
                   f'<script class="state-view" type="application/json">{json.dumps(state, ensure_ascii=False)}</script>'
                   "</body></html>")


@unittest.skipUnless(CHROME, "нет playwright/chromium")
class BrowseE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Mock)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_cli(self, data_dir, command="browse", search="search"):
        import time
        from sergiev_food import browser as br, cli
        real = br.YandexBrowser

        def factory(profile, **kw):
            kw.update(search_url=f"http://127.0.0.1:{PORT}/{search}?q={{q}}",
                      org_url=f"http://127.0.0.1:{PORT}/maps/org/{{id}}/",
                      sleep=lambda s: time.sleep(min(s, 0.05)), retries=2,
                      notify=lambda: setattr(Mock, "captcha_solved", True),  # «человек решил капчу»
                      launch_kwargs={"executable_path": CHROME[0], "args": ["--no-sandbox"]})
            kw["headless"] = True  # в тесте нет экрана
            return real(profile, **kw)

        br.YandexBrowser = factory
        try:
            # в тесте браузер headless, но капчу «решает» сигнал notify — отключаем запрет headless
            real_wait = real._wait_captcha

            def wait(self):
                self.headless = False
                real_wait(self)
            real._wait_captcha = wait
            return cli.main([command, "--data-dir", data_dir, "--delay", "0"])
        finally:
            br.YandexBrowser = real
            real._wait_captcha = real_wait

    def test_check_command(self):
        Mock.captcha_solved = True
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_cli(tmp, "check"), 0)

    def test_check_reports_problem_and_dumps_debug(self):
        Mock.captcha_solved = True
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_cli(tmp, "check", search="empty"), 1)
            self.assertTrue(glob.glob(os.path.join(tmp, "debug", "search_empty_*.png")))  # скриншот для диагностики

    def test_full_flow_and_resume(self):
        Mock.flaky_on, Mock.captcha_solved, Mock.captcha_shown = True, False, 0
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp)
            places = json.load(open(os.path.join(tmp, "places.json"), encoding="utf-8"))
            self.assertEqual(len(places), 30)
            self.assertGreaterEqual(Mock.captcha_shown, 1)

            def pl(i):
                return places[str(BASE + i)]

            # правильная организация, а не сосед с рейтингом 1.1
            self.assertEqual((pl(1)["rating"], pl(1)["rating_count"], pl(1)["parse_match"]), (3.1, 51, "exact"))
            self.assertEqual(pl(7)["status"], "permanently_closed")
            self.assertEqual(pl(GONE_ID)["status"], "removed")
            self.assertTrue(pl(OUTSIDE_ID)["out_of_city"])
            self.assertEqual((pl(NOJSON_ID)["rating"], pl(NOJSON_ID)["rating_count"], pl(NOJSON_ID)["parse_match"]),
                             (4.4, 77, "text"))
            self.assertEqual(pl(1)["name"], "Кафе 1")
            self.assertIn("Тест", pl(1)["address"])
            self.assertNotIn("enriched_at", pl(FLAKY_ID))   # не загрузилась — будет добрана
            self.assertEqual(pl(CAPTCHA_ID)["status"], "open")  # после «решения» капчи данные получены

            # второй запуск (сайт «починился»): добирает только оставшееся
            Mock.flaky_on = False
            self.run_cli(tmp)
            places = json.load(open(os.path.join(tmp, "places.json"), encoding="utf-8"))
            self.assertIn("enriched_at", places[str(BASE + FLAKY_ID)])
            self.assertEqual(places[str(BASE + FLAKY_ID)]["status"], "open")

            rows = list(csv.reader(open(os.path.join(tmp, "ranking.csv"), encoding="utf-8-sig"), delimiter=";"))
            names = [r[1] for r in rows[1:]]
            self.assertNotIn(f"Кафе {OUTSIDE_ID}", names)           # вне города исключено
            statuses = [r[2] for r in rows[1:]]
            first_closed = next(i for i, s in enumerate(statuses) if s in ("закрыто навсегда", "удалено/ликвидировано"))
            self.assertTrue(all(s in ("закрыто навсегда", "удалено/ликвидировано") for s in statuses[first_closed:]))


if __name__ == "__main__":
    unittest.main()
