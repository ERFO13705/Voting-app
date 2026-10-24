import argparse
import os
import sys

from . import discover as disc
from . import enrich as enr
from . import rank as rnk
from . import store


def build_parser():
    ap = argparse.ArgumentParser(prog="sergiev_food", description=__doc__)
    ap.add_argument("command", choices=["collect", "enrich", "rank", "all"],
                    help="collect — найти заведения; enrich — рейтинг и статус со страниц; "
                         "rank — построить таблицу; all — всё подряд")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--api-key", default=os.environ.get("YANDEX_API_KEY"),
                    help="ключ Yandex Search API (или переменная YANDEX_API_KEY)")
    ap.add_argument("--extra-urls", help="файл со ссылками на org-страницы, которых нет в выдаче API")
    ap.add_argument("--no-food-filter", action="store_true", help="не фильтровать по категориям общепита")
    ap.add_argument("--delay", type=float, default=5.0, help="пауза между страницами, сек (по умолчанию 5)")
    ap.add_argument("--limit", type=int, help="обработать не больше N организаций в enrich")
    ap.add_argument("--force", action="store_true", help="перезапросить уже обогащённые")
    ap.add_argument("--m", type=float, default=10, help="вес сомнения для взвешенного балла")
    ap.add_argument("--dump-dir", help="сохранять HTML страниц, которые не удалось разобрать")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    db = os.path.join(args.data_dir, "places.json")
    places = store.load(db)
    cmd = args.command

    if cmd in ("collect", "all"):
        if not args.api_key:
            sys.exit("Нужен ключ Yandex Search API: --api-key или YANDEX_API_KEY")
        places = disc.discover(args.api_key, places, food_filter=not args.no_food_filter)
        if args.extra_urls:
            with open(args.extra_urls, encoding="utf-8") as f:
                for oid in disc.ids_from_urls(f.read()):
                    places.setdefault(oid, {
                        "id": oid, "name": "", "address": "", "lat": None, "lon": None,
                        "categories": [], "phones": [], "website": "", "hours": "",
                        "url": f"https://yandex.ru/maps/org/{oid}/"})
        store.save(db, places)
        print(f"[collect] сохранено {len(places)} заведений -> {db}")

    if cmd in ("enrich", "all"):
        if not places:
            sys.exit("База пуста — сначала выполните collect")
        enr.enrich(places, delay=args.delay, limit=args.limit, force=args.force,
                   dump_dir=args.dump_dir, save=lambda: store.save(db, places))

    if cmd in ("rank", "all"):
        items = rnk.rank(places, m=args.m)
        rnk.write_csv(items, os.path.join(args.data_dir, "ranking.csv"))
        rnk.write_markdown(items, os.path.join(args.data_dir, "ranking.md"))
        print(f"[rank] {len(items)} заведений -> {args.data_dir}/ranking.csv, ranking.md")
        for p in items[:15]:
            print(f"{p['rank']:>3}. {p['name'][:38]:<38} {p.get('rating') or '-':>4} "
                  f"({rnk.votes(p):>4})  {rnk.STATUS_RU.get(p.get('status'), '')}")
    return 0
