import argparse
import os
import sys

from . import discover as disc
from . import enrich as enr
from . import rank as rnk
from . import store


def build_parser():
    ap = argparse.ArgumentParser(prog="sergiev_food", description=__doc__)
    ap.add_argument("command", choices=["browse", "collect", "enrich", "rank", "all"],
                    help="browse — всё через браузер без ключей (медленно); collect — найти заведения; enrich — рейтинг и статус со страниц; "
                         "rank — построить таблицу; all — всё подряд")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--api-key", default=os.environ.get("YANDEX_API_KEY"),
                    help="ключ Yandex Search API (или переменная YANDEX_API_KEY)")
    ap.add_argument("--extra-urls", help="файл со ссылками на org-страницы, которых нет в выдаче API")
    ap.add_argument("--no-food-filter", action="store_true", help="не фильтровать по категориям общепита")
    ap.add_argument("--delay", type=float, default=5.0, help="пауза между страницами, сек (по умолчанию 5)")
    ap.add_argument("--limit", type=int, help="обработать не больше N организаций в enrich")
    ap.add_argument("--force", action="store_true", help="перезапросить уже обогащённые")
    ap.add_argument("--keep-outside", action="store_true", help="не исключать заведения вне города")
    ap.add_argument("--headless", action="store_true", help="браузер без окна (капчу решить будет нельзя)")
    ap.add_argument("--m", type=float, default=10, help="вес сомнения для взвешенного балла")
    ap.add_argument("--dump-dir", help="сохранять HTML страниц, которые не удалось разобрать")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    db = os.path.join(args.data_dir, "places.json")
    places = store.load(db)
    cmd = args.command

    if cmd == "browse":
        from . import browser as br
        done_path = os.path.join(args.data_dir, "queries_done.json")
        done = store.load(done_path) or []
        if args.extra_urls:
            _add_extra(places, args.extra_urls)
        save = lambda: store.save(db, places)
        try:
            with br.YandexBrowser(os.path.join(args.data_dir, "browser-profile"),
                                  headless=args.headless) as b:
                br.browse_discover(b, places, done, lambda: (save(), store.save(done_path, done)))
                enr.enrich(places, delay=args.delay, limit=args.limit, force=args.force,
                           dump_dir=args.dump_dir, save=save, fetch=b.fetch_org)
        except KeyboardInterrupt:
            print("\nОстановлено. Прогресс сохранён — просто запустите снова, продолжит с того же места.")
            save()
        cmd = "rank"

    if cmd in ("collect", "all"):
        if not args.api_key:
            sys.exit("Нужен ключ Yandex Search API: --api-key или YANDEX_API_KEY")
        places = disc.discover(args.api_key, places, food_filter=not args.no_food_filter)
        if args.extra_urls:
            _add_extra(places, args.extra_urls)
        store.save(db, places)
        print(f"[collect] сохранено {len(places)} заведений -> {db}")

    if cmd in ("enrich", "all"):
        if not places:
            sys.exit("База пуста — сначала выполните collect")
        enr.enrich(places, delay=args.delay, limit=args.limit, force=args.force,
                   dump_dir=args.dump_dir, save=lambda: store.save(db, places))

    if cmd in ("rank", "all"):
        pool = places if args.keep_outside else {k: v for k, v in places.items() if not v.get("out_of_city")}
        if len(pool) < len(places):
            print(f"[rank] исключено как «вне города»: {len(places) - len(pool)} из {len(places)} "
                  f"(вернуть: --keep-outside)")
            if len(pool) < len(places) / 2:
                print("[rank] ВНИМАНИЕ: исключена половина и больше — возможно, фильтр по городу "
                      "ошибается; проверьте, запустив с --keep-outside")
        items = rnk.rank(pool, m=args.m)
        rnk.write_csv(items, os.path.join(args.data_dir, "ranking.csv"))
        rnk.write_markdown(items, os.path.join(args.data_dir, "ranking.md"))
        print(f"[rank] {len(items)} заведений -> {args.data_dir}/ranking.csv, ranking.md")
        for p in items[:15]:
            print(f"{p['rank']:>3}. {p['name'][:38]:<38} {p.get('rating') or '-':>4} "
                  f"({rnk.votes(p):>4})  {rnk.STATUS_RU.get(p.get('status'), '')}")
    return 0


def _add_extra(places, path):
    with open(path, encoding="utf-8") as f:
        for oid in disc.ids_from_urls(f.read()):
            places.setdefault(oid, {
                "id": oid, "name": "", "address": "", "lat": None, "lon": None,
                "categories": [], "phones": [], "website": "", "hours": "",
                "url": f"https://yandex.ru/maps/org/{oid}/"})
