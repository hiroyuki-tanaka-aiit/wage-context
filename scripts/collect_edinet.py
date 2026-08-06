import argparse
import csv
import datetime
import io
import json

import pathlib
import re

import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

from config import load_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA, CACHE = ROOT / "data", ROOT / "data" / "cache"
BASE = "https://api.edinet-fsa.go.jp/api/v2"
UA = {"User-Agent": "AIIT-SP-Kadai4/1.0 (student coursework)"}

TARGET_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

OWN = "CurrentYearInstant_NonConsolidatedMember"

TAGS = {
    "salary": ("jpcrp_cor:AverageAnnualSalaryInformation"
               "AboutReportingCompanyInformationAboutEmployees", OWN),
    "age": ("jpcrp_cor:AverageAgeYearsInformation"
            "AboutReportingCompanyInformationAboutEmployees", OWN),
    "service": ("jpcrp_cor:AverageLengthOfServiceYearsInformation"
                "AboutReportingCompanyInformationAboutEmployees", OWN),
    "employees": ("jpcrp_cor:NumberOfEmployees", OWN),
    "employees_group": ("jpcrp_cor:NumberOfEmployees", "CurrentYearInstant"),
    "address": ("jpcrp_cor:AddressOfRegisteredHeadquarterCoverPage",
                "FilingDateInstant"),
}

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県",
    "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県",
    "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府",
    "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
    "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
    "鹿児島県", "沖縄県",
]

MAJOR_CITIES = {
    "札幌市": "北海道", "仙台市": "宮城県", "さいたま市": "埼玉県", "千葉市": "千葉県",
    "横浜市": "神奈川県", "川崎市": "神奈川県", "相模原市": "神奈川県", "新潟市": "新潟県",
    "静岡市": "静岡県", "浜松市": "静岡県", "名古屋市": "愛知県", "京都市": "京都府",
    "大阪市": "大阪府", "堺市": "大阪府", "神戸市": "兵庫県", "岡山市": "岡山県",
    "広島市": "広島県", "北九州市": "福岡県", "福岡市": "福岡県", "熊本市": "熊本県",
    "青森市": "青森県", "盛岡市": "岩手県", "秋田市": "秋田県", "山形市": "山形県",
    "福島市": "福島県", "水戸市": "茨城県", "宇都宮市": "栃木県", "前橋市": "群馬県",
    "富山市": "富山県", "金沢市": "石川県", "福井市": "福井県", "甲府市": "山梨県",
    "長野市": "長野県", "岐阜市": "岐阜県", "津市": "三重県", "大津市": "滋賀県",
    "奈良市": "奈良県", "和歌山市": "和歌山県", "鳥取市": "鳥取県", "松江市": "島根県",
    "山口市": "山口県", "徳島市": "徳島県", "高松市": "香川県", "松山市": "愛媛県",
    "高知市": "高知県", "佐賀市": "佐賀県", "長崎市": "長崎県", "大分市": "大分県",
    "宮崎市": "宮崎県", "鹿児島市": "鹿児島県", "那覇市": "沖縄県",
    "姫路市": "兵庫県", "小樽市": "北海道",
}

SALARY_MIN, SALARY_MAX = 1_000_000, 30_000_000


class RateLimited(Exception):
    pass


def get(url, timeout=120, retries=5):
    for attempt in range(retries):
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(url, headers=UA),
                timeout=timeout).read()
        except Exception:
            time.sleep(2 ** attempt)
            continue
        if raw[:1] == b"{" and b'"StatusCode":"429"' in raw[:200]:
            time.sleep(2 ** attempt)
            continue
        return raw
    raise RateLimited(url.split("?")[0])


def to_number(s):
    if not s or s.strip() in ("－", "-", "―", ""):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def prefecture_of(address):
    if not address:
        return None
    address = re.sub(r"^[\s　]*〒?[\d０-９]{3}[-－ー―]?[\d０-９]{4}[\s　]*",
                     "", address.strip())
    pref = next((p for p in PREFECTURES if address.startswith(p)), None)
    if pref:
        return pref
    return next((p for city, p in MAJOR_CITIES.items()
                 if address.startswith(city)), None)


def month_days(year, month):
    day = datetime.date(year, month, 1)
    out = []
    while day.month == month:
        if day.weekday() < 5:
            out.append(day)
        day += datetime.timedelta(1)
    return out


def one_per_company(listed):
    uniq = {}
    for x in sorted(listed, key=lambda r: r.get("periodEnd") or ""):
        uniq[x.get("secCode")] = x
    return list(uniq.values())


def document_list(year, key, months=None):
    months = months or list(range(1, 13))
    tag = "all" if len(months) == 12 else "-".join(map(str, months))
    cached = CACHE / f"list_{year}_{tag}.json"
    if cached.exists():
        return one_per_company(json.loads(cached.read_text(encoding="utf-8")))
    days = [d for m in months for d in month_days(year, m)]

    def fetch_day(day):
        url = f"{BASE}/documents.json?date={day}&type=2&Subscription-Key={key}"
        return json.loads(get(url, 90)).get("results", []) or []

    with ThreadPoolExecutor(max_workers=3) as ex:
        docs = [d for day in ex.map(fetch_day, days) for d in day]
    listed = [x for x in docs
              if x.get("docTypeCode") == "120"
              and x.get("formCode") == "030000"
              and x.get("secCode")
              and x.get("csvFlag") == "1"]
    if not listed:
        raise RateLimited(f"{year}年の書類一覧が空")
    cached.write_text(json.dumps(listed, ensure_ascii=False), encoding="utf-8")
    return one_per_company(listed)


def fetch_zip(doc_id, key):
    cached = CACHE / f"{doc_id}.zip"
    if cached.exists():
        return cached.read_bytes(), True
    raw = get(f"{BASE}/documents/{doc_id}?type=5&Subscription-Key={key}")
    if raw[:2] != b"PK":
        raise RateLimited(doc_id)
    cached.write_bytes(raw)
    return raw, False


def extract(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    main = [n for n in z.namelist()
            if "jpcrp030000" in n and n.endswith(".csv")]
    if not main:
        return None
    found = {}
    body = io.StringIO(z.read(main[0]).decode("utf-16", "replace"))
    for row in csv.reader(body,
                          delimiter="\t"):
        if len(row) < 3:
            continue
        for field, (tag, context) in TAGS.items():
            if row[0] == tag and row[2] == context:
                found[field] = row[-1]
    address = (found.get("address") or "").strip()
    return {
        "salary": to_number(found.get("salary")),
        "age": to_number(found.get("age")),
        "service_years": to_number(found.get("service")),
        "employees": to_number(found.get("employees")),
        "employees_group": to_number(found.get("employees_group")),
        "address": address or None,
        "prefecture": prefecture_of(address),
    }


def collect_year(year, key, jpx, limit=None, workers=5):
    listed = document_list(year, key)
    targets = listed[:limit] if limit else listed
    stats = {"cache": 0, "ok": 0, "no_salary": 0, "error": 0}

    def work(rec):
        code4 = (rec.get("secCode") or "")[:-1]
        try:
            raw, cached = fetch_zip(rec["docID"], key)
            stats["cache"] += cached
            values = extract(raw)
        except Exception:
            stats["error"] += 1
            return None
        if not values or values["salary"] is None:
            stats["no_salary"] += 1
            return None
        stats["ok"] += 1
        info = jpx.get(code4, {})
        outlier = not (SALARY_MIN <= values["salary"] <= SALARY_MAX)
        return {"code": code4, "docID": rec["docID"], "year": year,
                "name": info.get("name") or rec.get("filerName"),
                "market": info.get("market"), "ind33": info.get("ind33"),
                "period_end": rec.get("periodEnd"), "outlier": outlier,
                **values}

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = [r for r in ex.map(work, targets) if r]
    elapsed = time.perf_counter() - started

    out = DATA / f"companies_{year}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    matched = sum(1 for r in results if r.get("ind33"))
    valid = sum(1 for r in results if not r["outlier"])
    print(f"{year}年 提出ぶん  対象 {len(targets):,} 社  {elapsed:.1f}秒"
          f"（1社 {elapsed / max(len(targets), 1) * 1000:.0f}ms、"
          f"キャッシュ {stats['cache']}）")
    print(f"        取得 {stats['ok']:,} / 給与なし {stats['no_salary']}"
          f" / エラー {stats['error']}"
          f" → 有効 {valid:,} 社、JPX結合 {matched:,} 社")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="対象年（その年に提出されたぶん）")
    ap.add_argument("--all-years", action="store_true",
                    help=f"{TARGET_YEARS} をまとめて処理")
    ap.add_argument("--limit", type=int, help="先頭 N 社だけ処理する（動作確認用）")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    key = load_key("EDINET_API_KEY")
    CACHE.mkdir(parents=True, exist_ok=True)
    jpx = {x["code"]: x for x in
           json.loads((DATA / "jpx.json").read_text(encoding="utf-8"))}

    years = TARGET_YEARS if args.all_years else [args.year or 2026]
    total = 0
    for year in years:
        total += len(collect_year(year, key, jpx, args.limit, args.workers))
    print(f"\n合計 {total:,} 件を data/companies_<年>.json に保存")


if __name__ == "__main__":
    main()
