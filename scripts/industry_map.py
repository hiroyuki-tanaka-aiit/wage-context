import collections
import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

MAPPING = {
    "建設業": ("direct", ["03"]),
    "繊維製品": ("direct", ["10"]),
    "パルプ・紙": ("direct", ["13"]),
    "化学": ("direct", ["15"]),
    "石油・石炭製品": ("direct", ["16"]),
    "ゴム製品": ("direct", ["18"]),
    "ガラス・土石製品": ("direct", ["20"]),
    "鉄鋼": ("direct", ["21"]),
    "非鉄金属": ("direct", ["22"]),
    "金属製品": ("direct", ["23"]),
    "輸送用機器": ("direct", ["30"]),
    "その他製品": ("direct", ["31"]),
    "電気・ガス業": ("direct", ["32"]),
    "情報・通信業": ("direct", ["37"]),
    "海運業": ("direct", ["47"]),
    "空運業": ("direct", ["48"]),
    "卸売業": ("direct", ["53"]),
    "小売業": ("direct", ["60"]),
    "銀行業": ("direct", ["68"]),
    "不動産業": ("direct", ["74"]),
    "鉱業": ("direct", ["02"]),

    "食料品": ("merge", ["08", "09"]),
    "機械": ("merge", ["24", "25", "26"]),
    "電気機器": ("merge", ["27", "28", "29"]),
    "陸運業": ("merge", ["44", "45", "46"]),
    "倉庫・運輸関連業": ("merge", ["49", "50"]),

    "医薬品": ("coarse", ["15"]),
    "精密機器": ("coarse", ["26"]),
    "証券、商品先物取引業": ("coarse", ["67"]),
    "保険業": ("coarse", ["67"]),
    "その他金融業": ("coarse", ["67"]),

    "サービス業": ("none", []),
    "水産・農林業": ("none", []),
}

TIER_LABEL = {"direct": "1対1で対応", "merge": "1対多（加重平均）",
              "coarse": "上位分類に丸める", "none": "対応先が無い"}


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def industry_names():
    return {c["code"]: c["name"] for c in load_json("estat_ind.json")}


def resolve(ind33, estat_mean, age_code):
    entry = MAPPING.get(ind33)
    if entry is None or entry[0] == "none":
        return None
    codes = [c for c in entry[1]
             if c in estat_mean and age_code in estat_mean[c]]
    if not codes:
        return None
    rows = [estat_mean[c][age_code] for c in codes]
    weights = [r.get("労働者数") or 0 for r in rows]
    total = sum(weights)
    if total == 0:
        weights, total = [1] * len(rows), len(rows)

    def weighted(key):
        pairs = [(r.get(key), w) for r, w in zip(rows, weights)
                 if r.get(key) is not None]
        if not pairs:
            return None
        return sum(v * w for v, w in pairs) / sum(w for _, w in pairs)

    return {k: weighted(k) for k in
            ("きまって支給する現金給与額", "所定内給与額", "年間賞与その他特別給与額",
             "年齢", "勤続年数", "超過実労働時間数", "労働者数")}


def resolve_quantile(ind33, quant, mean, age_code, qcode):
    entry = MAPPING.get(ind33)
    codes = entry[1] if entry and entry[0] != "none" else []
    vals, weights = [], []
    for c in codes:
        v = quant.get(c, {}).get(age_code, {}).get(qcode)
        if v is None:
            continue
        vals.append(v)
        row = mean.get(c, {}).get(age_code, {}) or {}
        weights.append(row.get("労働者数") or 1)
    if not vals:
        return None
    return sum(v * w for v, w in zip(vals, weights)) / sum(weights)


def annual_income(row):
    if not row:
        return None
    monthly = row.get("きまって支給する現金給与額")
    bonus = row.get("年間賞与その他特別給与額")
    if monthly is None or bonus is None:
        return None
    return (monthly * 12 + bonus) * 1000


def main():
    companies = []
    for path in sorted(DATA.glob("companies_*.json")):
        companies += json.loads(path.read_text(encoding="utf-8"))
    names = industry_names()

    by_tier = collections.defaultdict(list)
    counts = collections.Counter(c["ind33"] for c in companies
                                 if c.get("ind33"))
    for ind33, n in counts.items():
        tier = MAPPING.get(ind33, ("none", []))[0]
        by_tier[tier].append((ind33, n))

    total = sum(counts.values())
    print(f"JPX 33業種 → 賃金構造基本統計調査 の対応（延べ {total:,} 社）\n")
    for tier in ("direct", "merge", "coarse", "none"):
        rows = sorted(by_tier[tier], key=lambda x: -x[1])
        n = sum(v for _, v in rows)
        print(f"■ {TIER_LABEL[tier]}: {n:,}社 ({n / total * 100:.0f}%)")
        for ind33, cnt in rows:
            codes = MAPPING.get(ind33, ("none", []))[1]
            dest = " + ".join(names.get(c, c).split(maxsplit=1)[-1][:18]
                              for c in codes)
            print(f"     {cnt:>4}社  {ind33:<16} → {dest or '（なし）'}")
        print()

    unmapped = [k for k in counts if k not in MAPPING]
    if unmapped:
        print(f"対応表に無い業種: {unmapped}")


if __name__ == "__main__":
    main()
