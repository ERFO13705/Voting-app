"""Поиск заведений через официальный Yandex Search API (поиск по организациям).

Ключ: https://developer.tech.yandex.ru/ -> «JavaScript API и HTTP Геокодер»/«Поиск по организациям».
Лимиты API: до 50 результатов на запрос, поэтому город режется на квадраты,
а по каждому квадрату идёт набор запросов по категориям.
"""
import json
import re
import time
import urllib.parse
import urllib.request

API_URL = "https://search-maps.yandex.ru/v1/"
# lon_min, lat_min, lon_max, lat_max — с запасом вокруг города, лишнее отсекается по адресу
CITY_BBOX = (38.03, 56.26, 38.24, 56.37)
CITY_RE = re.compile(r"Сергиев\s+Посад(?!ск)", re.IGNORECASE)

QUERIES = [
    "кафе", "ресторан", "бар", "паб", "кофейня", "пиццерия", "столовая",
    "фастфуд", "быстрое питание", "суши", "пекарня", "булочная", "шаурма",
    "бистро", "пельменная", "блинная", "чайхана", "кондитерская", "закусочная",
    "доставка еды", "банкетный зал", "кальянная",
]
FOOD_CATEGORY_RE = re.compile(
    "кафе|ресторан|бар\\b|паб|кофейн|пиццер|столов|фастфуд|быстрого питания|"
    "суши|пекарн|булочн|шаурм|бистро|пельменн|блинн|чайхан|кондитер|закусочн|"
    "доставка еды|доставка пиццы|банкет|кальян|чебуречн|шашлычн|гриль|пончик|"
    "мороженое|караоке|кулинар|магазин-кафе|общественное питание|кейтеринг",
    re.IGNORECASE,
)


def split_bbox(bbox, nx=2, ny=2):
    lon0, lat0, lon1, lat1 = bbox
    dx, dy = (lon1 - lon0) / nx, (lat1 - lat0) / ny
    return [
        (lon0 + i * dx, lat0 + j * dy, lon0 + (i + 1) * dx, lat0 + (j + 1) * dy)
        for i in range(nx) for j in range(ny)
    ]


def parse_feature(feature):
    """GeoJSON-feature из ответа API -> запись; None, если это не организация."""
    props = feature.get("properties") or {}
    meta = props.get("CompanyMetaData")
    if not meta or not meta.get("id"):
        return None
    lon, lat = (feature.get("geometry", {}).get("coordinates") or [None, None])[:2]
    org_id = str(meta["id"])
    return {
        "id": org_id,
        "name": meta.get("name") or props.get("name") or "",
        "address": meta.get("address") or props.get("description") or "",
        "lat": lat,
        "lon": lon,
        "categories": [c.get("name", "") for c in meta.get("Categories", [])],
        "phones": [p.get("formatted", "") for p in meta.get("Phones", [])],
        "website": meta.get("url") or "",
        "hours": (meta.get("Hours") or {}).get("text") or "",
        "url": f"https://yandex.ru/maps/org/{org_id}/",
    }


def is_target(place, food_filter=True):
    if not CITY_RE.search(place["address"]):
        return False
    if food_filter and not any(FOOD_CATEGORY_RE.search(c) for c in place["categories"]):
        return False
    return True


def fetch_page(api_key, text, bbox, skip=0, timeout=30):
    params = {
        "apikey": api_key, "text": text, "lang": "ru_RU", "type": "biz",
        "bbox": "%f,%f~%f,%f" % (bbox[0], bbox[1], bbox[2], bbox[3]),
        "rspn": 1, "results": 50, "skip": skip,
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def discover(api_key, existing=None, food_filter=True, pause=0.3, log=print,
             fetch=fetch_page, max_skip=1000):
    """Возвращает словарь {id: запись}, дополняя existing."""
    places = dict(existing or {})
    tiles = split_bbox(CITY_BBOX)
    for query in QUERIES:
        added = 0
        for tile in tiles:
            skip = 0
            while skip < max_skip:
                data = fetch(api_key, query, tile, skip)
                features = data.get("features", [])
                for feat in features:
                    place = parse_feature(feat)
                    if place and is_target(place, food_filter) and place["id"] not in places:
                        places[place["id"]] = place
                        added += 1
                if len(features) < 50:
                    break
                skip += 50
                time.sleep(pause)
            time.sleep(pause)
        log(f"[collect] «{query}»: +{added}, всего {len(places)}")
    return places


ORG_URL_RE = re.compile(r"yandex\.[a-z]+/maps/(?:[^/\s]+/)?org/(?:[^/\s]+/)?(\d{5,})")


def ids_from_urls(text):
    """Достаёт ID организаций из ссылок вида https://yandex.ru/maps/org/dodo_pitstsa/1725406121/..."""
    return list(dict.fromkeys(ORG_URL_RE.findall(text)))
