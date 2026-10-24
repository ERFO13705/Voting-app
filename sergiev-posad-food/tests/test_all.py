import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sergiev_food import discover as d, enrich as e, rank as r  # noqa: E402


def feature(oid, name, address, cats):
    return {"geometry": {"coordinates": [38.13, 56.31]},
            "properties": {"CompanyMetaData": {
                "id": oid, "name": name, "address": address,
                "Categories": [{"name": c} for c in cats],
                "Phones": [{"formatted": "+7 (496) 000-00-00"}],
                "Hours": {"text": "ежедневно, 10:00–22:00"}}}}


def page(org_id, rating, rc, rev, extra="", title="Кафе, Сергиев Посад — Яндекс Карты"):
    org = {"id": org_id, "title": "x", "ratingData": {
        "ratingValue": rating, "ratingCount": rc, "reviewCount": rev}}
    if extra:
        org["flag"] = extra
    state = {"orgpage": org,
        "nearby": [{"id": "999", "ratingData": {"ratingValue": 1.0, "ratingCount": 1, "reviewCount": 1}}]}
    return (f"<html><head><title>{title}</title></head><body>"
            f'<script type="application/json" class="state-view">{json.dumps(state, ensure_ascii=False)}</script>'
            "</body></html>")


class Discover(unittest.TestCase):
    def test_parse_and_filter(self):
        ok = d.parse_feature(feature(1725406121, "Додо Пицца", "Московская область, Сергиев Посад, пр. Красной Армии, 1", ["Пиццерия"]))
        self.assertEqual(ok["url"], "https://yandex.ru/maps/org/1725406121/")
        self.assertTrue(d.is_target(ok))
        other_city = d.parse_feature(feature(2, "Х", "Москва, ул. Ленина, 1", ["Кафе"]))
        self.assertFalse(d.is_target(other_city))
        district = d.parse_feature(feature(3, "Х", "Сергиево-Посадский городской округ, село Н", ["Кафе"]))
        self.assertFalse(d.is_target(district))
        shop = d.parse_feature(feature(4, "Х", "Сергиев Посад, ул. А, 1", ["Автосервис"]))
        self.assertFalse(d.is_target(shop))
        self.assertTrue(d.is_target(shop, food_filter=False))
        self.assertIsNone(d.parse_feature({"properties": {}}))

    def test_discover_paginates_and_dedupes(self):
        addr = "Сергиев Посад, ул. А, "
        pages = {0: [feature(i + 1, f"К{i}", addr + str(i), ["Кафе"]) for i in range(50)],
                 50: [feature(i + 1, f"К{i}", addr + str(i), ["Кафе"]) for i in range(40, 60)]}
        calls = []

        def fake(key, text, bbox, skip):
            calls.append(skip)
            return {"features": pages[skip] if text == "кафе" and bbox == d.split_bbox(d.CITY_BBOX)[0] else []}

        orig = d.QUERIES
        d.QUERIES = ["кафе"]
        try:
            res = d.discover("k", fetch=fake, pause=0, log=lambda *_: None)
        finally:
            d.QUERIES = orig
        self.assertEqual(len(res), 60)
        self.assertIn(50, calls)

    def test_ids_from_urls(self):
        t = ("https://yandex.ru/maps/org/dodo_pitstsa/1725406121/?ll=38.1&mode=search\n"
             "https://yandex.ru/maps/org/1725406121/\nhttps://yandex.ru/maps/10748/org/foo/42424242/")
        self.assertEqual(d.ids_from_urls(t), ["1725406121", "42424242"])


class Enrich(unittest.TestCase):
    def test_exact_block_wins_over_neighbours(self):
        info = e.parse_org_page(page("111", 4.6, 250, 80), "111")
        self.assertEqual((info["rating"], info["rating_count"], info["review_count"], info["status"], info["match"]),
                         (4.6, 250, 80, "open", "exact"))

    def test_closed_markers(self):
        self.assertEqual(e.parse_org_page(page("1", 4.0, 5, 1, extra="Закрыто навсегда"), "1")["status"], "permanently_closed")
        self.assertEqual(e.parse_org_page(page("1", 4.0, 5, 1, extra="Временно закрыто"), "1")["status"], "temporarily_closed")

    def test_garbage_page(self):
        self.assertEqual(e.parse_org_page("<html></html>", "1")["status"], "unknown")

    def test_enrich_loop_handles_captcha_and_404(self):
        places = {"1": {"id": "1", "name": "А"}, "2": {"id": "2", "name": "Б"}, "3": {"id": "3", "name": "В"}}
        seq = {"1": page("1", 4.5, 10, 3), "2": None}

        def fetch(oid):
            if oid == "3":
                raise e.CaptchaError("x")
            return seq[oid]

        saves = []
        done = e.enrich(places, fetch=fetch, sleep=lambda *_: None, log=lambda *_: None, save=lambda: saves.append(1))
        self.assertFalse(done)
        self.assertEqual(places["1"]["rating"], 4.5)
        self.assertEqual(places["2"]["status"], "removed")
        self.assertNotIn("enriched_at", places["3"])  # доберётся при следующем запуске
        self.assertEqual(len(saves), 2)


class Rank(unittest.TestCase):
    def test_order(self):
        P = lambda i, rating, n, status="open": {"id": i, "name": i, "rating": rating, "rating_count": n, "status": status,
                                                  "categories": [], "phones": [], "url": "u"}
        places = {p["id"]: p for p in [
            P("few5", 5.0, 2), P("many47", 4.7, 800), P("closedbest", 4.9, 900, "permanently_closed"),
            P("norating", None, 0), P("mid", 4.2, 100), P("low1", 3.4, 50), P("low2", 3.6, 50), P("temp", 4.8, 300, "temporarily_closed")]}
        order = [p["id"] for p in r.rank(places)]
        self.assertEqual(order, ["many47", "few5", "mid", "low2", "low1", "norating", "temp", "closedbest"])

    def test_outputs(self):
        items = r.rank({"1": {"id": "1", "name": "А|Б", "rating": 4.5, "rating_count": 10, "status": "open",
                              "categories": ["Кафе"], "phones": [], "url": "u", "address": "a"}})
        with tempfile.TemporaryDirectory() as t:
            r.write_csv(items, os.path.join(t, "r.csv"))
            r.write_markdown(items, os.path.join(t, "r.md"))
            self.assertIn("работает", open(os.path.join(t, "r.csv"), encoding="utf-8-sig").read())
            self.assertIn("А/Б", open(os.path.join(t, "r.md"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
