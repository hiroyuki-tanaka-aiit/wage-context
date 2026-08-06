import bisect
import collections
import json
import pathlib
import statistics

import industry_map as im

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

AGE_BRACKETS = [
    ("02", 0), ("03", 20), ("04", 25), ("05", 30), ("06", 35), ("07", 40),
    ("08", 45), ("09", 50), ("10", 55), ("11", 60), ("12", 65), ("13", 70),
]
QUANTILES = [("1280", 0.10), ("1290", 0.25), ("1300", 0.50),
             ("1310", 0.75), ("1320", 0.90)]


def age_code(age):
    if age is None:
        return None
    code = "02"
    for c, lower in AGE_BRACKETS:
        if age >= lower:
            code = c
    return code


def annual_quantiles(ind33, age_c, mean, quant):
    stats = im.resolve(ind33, mean, age_c)
    if not stats:
        return None
    monthly = stats.get("きまって支給する現金給与額")
    inner = stats.get("所定内給与額")
    bonus = stats.get("年間賞与その他特別給与額")
    if not monthly or not inner or bonus is None or inner == 0:
        return None
    scale = (monthly * 12 + bonus) / (inner * 12)

    codes = im.MAPPING.get(ind33, ("none", []))[1]
    points = []
    for qcode, prob in QUANTILES:
        vals, weights = [], []
        for c in codes:
            v = quant.get(c, {}).get(age_c, {}).get(qcode)
            w = (mean.get(c, {}).get(age_c, {}) or {}).get("労働者数") or 1
            if v is not None:
                vals.append(v)
                weights.append(w)
        if not vals:
            return None
        merged = sum(v * w for v, w in zip(vals, weights)) / sum(weights)
        points.append((prob, merged * 12 * scale * 1000))
    return points


def percentile_of(salary, points):
    values = [v for _, v in points]
    probs = [p for p, _ in points]
    if salary <= values[0]:
        return probs[0] * salary / values[0], True
    if salary >= values[-1]:
        span = values[-1] - values[-2]
        extra = ((salary - values[-1]) / span * (probs[-1] - probs[-2])
                 if span else 0)
        return min(0.99, probs[-1] + extra), True
    i = bisect.bisect_left(values, salary)
    v0, v1 = values[i - 1], values[i]
    p0, p1 = probs[i - 1], probs[i]
    return p0 + (p1 - p0) * (salary - v0) / (v1 - v0), False


MIN_PEERS = 10


def peer_baselines(companies):
    cells = collections.defaultdict(list)
    for c in companies:
        cells[(c["year"], c["ind33"], c["age_bracket"])].append(c["salary"])
        cells[(c["year"], c["ind33"])].append(c["salary"])
    return cells


def peer_median(cells, company):
    cell = (company["year"], company["ind33"], company["age_bracket"])
    for key, basis in ((cell,
                        "業種×年齢階級"),
                       ((company["year"], company["ind33"]), "業種")):
        peers = cells[key]
        if len(peers) - 1 >= MIN_PEERS:
            others = list(peers)
            others.remove(company["salary"])
            return statistics.median(others), basis
    return None, None


def stats_year(company_year, available):
    y = str(company_year)
    if y in available:
        return y, False
    latest = max(available)
    return latest, True


def main():
    mean_by_year = json.loads(
        (DATA / "estat_mean.json").read_text(encoding="utf-8"))
    quant_by_year = json.loads(
        (DATA / "estat_quantile.json").read_text(encoding="utf-8"))
    available = set(mean_by_year) & set(quant_by_year)

    companies = []
    for path in sorted(DATA.glob("companies_*.json")):
        companies += json.loads(path.read_text(encoding="utf-8"))

    usable, skipped = [], collections.Counter()
    for c in companies:
        if c.get("outlier") or not c.get("salary"):
            skipped["外れ値・給与なし"] += 1
        elif not c.get("ind33"):
            skipped["JPXと結合できず業種不明"] += 1
        elif age_code(c.get("age")) is None:
            skipped["平均年齢なし"] += 1
        else:
            c["age_bracket"] = age_code(c["age"])
            usable.append(c)
    cells = peer_baselines(usable)

    results = []
    for c in usable:
        code = c["age_bracket"]
        syear, substituted = stats_year(c["year"], available)
        points = annual_quantiles(c["ind33"], code,
                                  mean_by_year[syear], quant_by_year[syear])
        no_national = substituted or points is None
        if points is None:
            skipped["業種の対応先なし（全国基準のみ出せない）"] += 1
        nat_mean = im.annual_income(
            im.resolve(c["ind33"], mean_by_year[syear], code))
        listed, basis = peer_median(cells, c)
        pct, outside = (percentile_of(c["salary"], points) if points
                        else (None, None))
        row = {
            **{k: c[k] for k in ("code", "name", "year", "market", "ind33",
                                 "salary", "age", "service_years",
                                 "employees", "employees_group",
                                 "prefecture", "period_end", "age_bracket")},
            "stats_year": int(syear),
            "stats_substituted": substituted,
            "entry_age": (round(c["age"] - c["service_years"], 1)
                          if c.get("service_years") is not None else None),
            "percentile": round(pct, 4) if pct is not None else None,
            "percentile_outside": outside,
            "national_mean": round(nat_mean) if nat_mean else None,
            "national_median": round(points[2][1]) if points else None,
            "ratio_to_national": (round(c["salary"] / nat_mean, 3)
                                  if nat_mean else None),
            "listed_median": round(listed) if listed else None,
            "listed_basis": basis,
            "ratio_to_listed": (round(c["salary"] / listed, 3)
                                if listed else None),
        }
        if no_national:
            for k in ("percentile", "percentile_outside", "national_mean",
                      "national_median", "ratio_to_national"):
                row[k] = None
        results.append(row)

    tmp = DATA / "analysis.json.tmp"
    tmp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA / "analysis.json")
    report(results, companies, skipped)


def report(results, companies, skipped):
    aligned = max((r["year"] for r in results if r["ratio_to_national"]),
                  default=None)
    with_nat = sum(1 for r in results if r["ratio_to_national"] is not None)
    print(f"分析対象 {len(results):,} 社 / 全 {len(companies):,} 社")
    print(f"   うち全国基準が出せる {with_nat:,} 社 "
          f"（残りは実額と対上場同業のみ {len(results) - with_nat:,} 社）")
    for reason, n in skipped.most_common():
        head = "内訳" if "全国基準のみ" in reason else "除外"
        print(f"   {head} {reason:<32} {n:>5} 社")

    def med(rows_, key):
        v = [r[key] for r in rows_ if r[key]]
        return statistics.median(v) if v else float("nan")

    print("\n=== 基準ごとの倍率の中央値 ===")
    print(f"{'年':<6}{'対 全国平均':>14}{'対 上場同業':>14}   基準の状態")
    for y in sorted({r["year"] for r in results}):
        g = [r for r in results if r["year"] == y]
        sub = g[0]["stats_substituted"]
        note = f"統計は{g[0]['stats_year']}年で代用" if sub else "統計と年度が一致"
        print(f"{y:<6}{med(g, 'ratio_to_national'):>13.3f}倍"
              f"{med(g, 'ratio_to_listed'):>13.3f}倍   {note}")
    print("   対 上場同業 は自前計算なので、どの年も遅れがない")

    latest = [r for r in results
              if r["year"] == aligned and r["ratio_to_national"]]
    above = sum(1 for r in latest if r["ratio_to_national"] >= 1)
    print(f"\n=== {aligned}年（統計と年度を揃えた比較）{len(latest):,} 社 ===")
    pct = above / len(latest) * 100
    print(f"   全国平均を上回る会社 {above:,}/{len(latest):,} = {pct:.0f}%")

    print(f"\n業種別（{aligned}年、10社以上）")
    by_ind = collections.defaultdict(list)
    for r in latest:
        by_ind[r["ind33"]].append(r)
    rows = sorted(((k, med(v, "ratio_to_national"),
                    med(v, "ratio_to_listed"), len(v))
                   for k, v in by_ind.items() if len(v) >= 10),
                  key=lambda x: -x[1])
    print(f"   {'業種':<16} {'社数':>5}  {'対全国平均':>9} {'対上場同業':>10}")
    for name, rn, rl, n in rows[:10] + [("…", 0, 0, 0)] + rows[-5:]:
        if name == "…":
            print("   …")
            continue
        print(f"   {name:<16} {n:>4}社  {rn:>8.2f}倍 {rl:>9.2f}倍")

    basis = collections.Counter(r["listed_basis"] for r in results)
    print("\n上場同業の基準の粒度: " +
          " / ".join(f"{k or '作れず'} {v:,}社" for k, v in basis.most_common()))

    print(f"\n市場区分別（{aligned}年）")
    for mk in ("プライム", "スタンダード", "グロース"):
        rs = [r for r in latest if r["market"] == mk]
        if not rs:
            continue
        print(f"   {mk:<8} {len(rs):>4}社  "
              f"平均年齢 {statistics.median([r['age'] for r in rs]):.1f}歳  "
              f"対全国平均 {med(rs, 'ratio_to_national'):.2f}倍  "
              f"対上場同業 {med(rs, 'ratio_to_listed'):.2f}倍")


if __name__ == "__main__":
    main()
