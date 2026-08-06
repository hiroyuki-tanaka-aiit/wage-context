import json

import pathlib

import time
import urllib.request

from config import load_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
UA = {"User-Agent": "AIIT-SP-Kadai4/1.0 (student coursework)"}
LIMIT = 100_000

MEAN_TABLE = "0003425893"
QUANT_TABLE = "0003425913"

MEAN_ITEMS = {
    "33": "年齢", "34": "勤続年数", "38": "超過実労働時間数",
    "40": "きまって支給する現金給与額", "42": "所定内給与額",
    "44": "年間賞与その他特別給与額", "45": "労働者数",
}
YEARS = ["2020000000", "2021000000", "2022000000", "2023000000"]


def fetch_all(app_id, table, params):
    values, start, page = [], 1, 0
    while True:
        url = (f"{BASE}/getStatsData?appId={app_id}&statsDataId={table}"
               f"{params}&limit={LIMIT}&startPosition={start}")
        body = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=300).read())
        stat = body["GET_STATS_DATA"]["STATISTICAL_DATA"]
        values += stat["DATA_INF"]["VALUE"]
        page += 1
        next_key = stat["RESULT_INF"].get("NEXT_KEY")
        print(f"    ページ{page}: 累計 {len(values):,} 件 / 全体 "
              f"{stat['RESULT_INF'].get('TOTAL_NUMBER'):,}")
        if not next_key:
            return values
        start = int(next_key)


def to_number(s):
    if s is None or str(s).strip() in ("－", "-", "***", "X", ""):
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def main():
    app_id = load_key("ESTAT_APP_ID")

    print("平均値（産業 × 年齢階級）を取得")
    t = time.perf_counter()
    params = ("&cdTab=" + ",".join(MEAN_ITEMS)
              + "&cdCat01=01"
              + "&cdCat03=01"
              + "&cdCat05=01"
              + "&cdCat06=02"
              + "&cdTime=" + ",".join(YEARS))
    mean = {}
    for v in fetch_all(app_id, MEAN_TABLE, params):
        item = MEAN_ITEMS.get(v.get("@tab"))
        if item is None:
            continue
        industry, age = v.get("@cat02"), v.get("@cat04")
        year = v.get("@time")[:4]
        cell = mean.setdefault(year, {}).setdefault(industry, {})
        cell = cell.setdefault(age, {})
        cell[item] = to_number(v.get("$"))
    (DATA / "estat_mean.json").write_text(
        json.dumps(mean, ensure_ascii=False), encoding="utf-8")
    print(f"  → estat_mean.json  {len(mean)} 年分  "
          f"{time.perf_counter() - t:.1f}秒\n")

    print("分位数（産業 × 年齢階級 × 賃金階級）を取得")
    t = time.perf_counter()
    params = ("&cdTab=48"
              + "&cdCat02=01"
              + "&cdCat04=02"
              + "&cdCat06=01"
              + "&cdCat07=01"
              + "&cdTime=" + ",".join(YEARS))
    quant = {}
    for v in fetch_all(app_id, QUANT_TABLE, params):
        industry, age = v.get("@cat01"), v.get("@cat03")
        band, year = v.get("@cat05"), v.get("@time")[:4]
        cell = quant.setdefault(year, {}).setdefault(industry, {})
        cell = cell.setdefault(age, {})
        cell[band] = to_number(v.get("$"))
    (DATA / "estat_quantile.json").write_text(
        json.dumps(quant, ensure_ascii=False), encoding="utf-8")
    print(f"  → estat_quantile.json  {len(quant)} 年分  "
          f"{time.perf_counter() - t:.1f}秒")


if __name__ == "__main__":
    main()
