import collections
import json
import pathlib
import statistics

from flask import Flask, jsonify, render_template, request

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "scripts"))
import industry_map as im  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
app = Flask(__name__)

MARKET_COLORS = {"プライム": "#1f77b4", "スタンダード": "#ff7f0e", "グロース": "#2ca02c"}
CURVE_STYLE = {"平均": {"dash": "solid", "width": 2.5, "color": "#d62728"},
               "中央値": {"dash": "dash", "width": 2.5, "color": "#2b3a55"},
               "第1四分位": {"dash": "dot", "width": 1.5, "color": "#8a8a8a"},
               "第3四分位": {"dash": "dot", "width": 1.5, "color": "#8a8a8a"}}
CURVE_AGES = [("03", 22), ("04", 27), ("05", 32), ("06", 37), ("07", 42),
              ("08", 47), ("09", 52), ("10", 57), ("11", 62)]
CURVE_QUANTILES = (("第1四分位", "1290"), ("中央値", "1300"), ("第3四分位", "1310"))


def load():
    rows = json.loads((DATA / "analysis.json").read_text(encoding="utf-8"))
    mean = json.loads((DATA / "estat_mean.json").read_text(encoding="utf-8"))
    quant = json.loads(
        (DATA / "estat_quantile.json").read_text(encoding="utf-8"))
    return rows, mean, quant


ROWS, MEAN, QUANT = load()
YEARS = sorted({r["year"] for r in ROWS})
INDUSTRIES = sorted({r["ind33"] for r in ROWS})
PREFECTURES = sorted({r["prefecture"] for r in ROWS if r.get("prefecture")})

DEFAULT_YEAR = max((y for y in YEARS
                    if any(r["ratio_to_national"] for r in ROWS
                           if r["year"] == y)),
                   default=YEARS[-1])


def year_caveats():
    per_month = collections.defaultdict(collections.Counter)
    for r in ROWS:
        per_month[r["year"]][(r.get("period_end") or "????-??")[5:7]] += 1

    out = {}
    for i, year in enumerate(YEARS):
        notes, missing = [], []
        if any(r["stats_substituted"] for r in ROWS if r["year"] == year):
            notes.append("統計が未公表なので、全国と比べる値は出していない"
                         "（実額・従業員数・年齢・対上場同業だけになる）")
        if i:
            prev = per_month[YEARS[i - 1]]
            missing = [m for m, n in sorted(prev.items())
                       if per_month[year].get(m, 0) < n * 0.5]
        if missing:
            lost = (sum(prev[m] for m in missing)
                    - sum(per_month[year].get(m, 0) for m in missing))
            months = "・".join(m.lstrip("0") + "月" for m in missing)
            notes.append(f"{months}決算の会社が未提出"
                         f"（前年比 約{lost:,}社ぶん不足）")
        out[year] = notes
    return out


CAVEATS = year_caveats()


def subset(year=None, industry=None, market=None):
    out = ROWS
    if year:
        out = [r for r in out if r["year"] == int(year)]
    if industry and industry != "すべて":
        out = [r for r in out if r["ind33"] == industry]
    if market and market != "すべて":
        out = [r for r in out if r["market"] == market]
    return out


@app.route("/")
def index():
    return render_template("index.html", years=YEARS, industries=INDUSTRIES,
                           caveats=CAVEATS, market_colors=MARKET_COLORS,
                           prefectures=PREFECTURES,
                           markets=list(MARKET_COLORS),
                           default_year=DEFAULT_YEAR)


MIN_TREND = 10


@app.route("/api/industry_trend")
def api_industry_trend():
    years = [y for y in YEARS
             if any(r["ratio_to_national"] for r in ROWS if r["year"] == y)]
    if len(years) < 2:
        return jsonify({"rows": []})
    first, last = years[0], years[-1]

    def listed(year, ind):
        v = [r["salary"] for r in ROWS
             if r["year"] == year and r["ind33"] == ind]
        return statistics.median(v) if len(v) >= MIN_TREND else None

    def whole(year, ind):
        return im.annual_income(im.resolve(ind, MEAN[str(year)], "01"))

    out = []
    for ind in sorted({r["ind33"] for r in ROWS}):
        a, b = listed(first, ind), listed(last, ind)
        c, d = whole(first, ind), whole(last, ind)
        if not all((a, b, c, d)):
            continue
        out.append({
            "ind": ind,
            "n": sum(1 for r in ROWS
                     if r["year"] == last and r["ind33"] == ind),
            "listed_growth": round(b / a - 1, 4),
            "whole_growth": round(d / c - 1, 4),
            "listed_first": a, "listed_last": b,
            "whole_first": c, "whole_last": d,
        })
    out.sort(key=lambda r: r["listed_growth"])
    behind = sum(1 for r in out if r["listed_growth"] < r["whole_growth"])
    return jsonify({
        "first": first, "last": last, "rows": out, "behind": behind,
        "listed_median": round(
            statistics.median([r["listed_growth"] for r in out]), 4),
        "whole_median": round(
            statistics.median([r["whole_growth"] for r in out]), 4),
    })


def company_points(rows):
    traces = []
    for market, color in MARKET_COLORS.items():
        pts = [r for r in rows if r["market"] == market]
        if not pts:
            continue
        traces.append({
            "type": "scatter", "mode": "markers", "name": market,
            "x": [r["age"] for r in pts], "y": [r["salary"] for r in pts],
            "marker": {"size": 6, "opacity": 0.6, "color": color},
            "text": [f"{r['name']}（対全国平均{r['ratio_to_national']:.2f}倍）"
                     if r["ratio_to_national"] else r["name"] for r in pts],
            "hovertemplate": ("%{text}<br>"
                              "%{x:.1f}歳 / %{y:,.0f}円<extra></extra>"),
        })
    return traces


def national_curves(year, industry):
    sy = str(year)
    if sy not in MEAN:
        return [], "統計なし"
    mean_y, quant_y = MEAN[sy], QUANT[sy]
    whole = industry == "すべて"
    xs, curves = [], {name: [] for name in CURVE_STYLE}
    for code, lower in CURVE_AGES:
        stats = (mean_y.get("01") or {}).get(code) if whole \
            else im.resolve(industry, mean_y, code)
        if not stats:
            continue
        inner = stats.get("所定内給与額")
        monthly = stats.get("きまって支給する現金給与額")
        bonus = stats.get("年間賞与その他特別給与額")
        if not inner or not monthly or bonus is None:
            continue
        scale = (monthly * 12 + bonus) / (inner * 12)
        band = {label: (quant_y.get("01", {}).get(code, {}).get(qcode) if whole
                        else im.resolve_quantile(
                            industry, quant_y, mean_y, code, qcode))
                for label, qcode in CURVE_QUANTILES}
        if not any(band.values()):
            continue
        xs.append(lower)
        curves["平均"].append((monthly * 12 + bonus) * 1000)
        for label, v in band.items():
            curves[label].append(v * 12 * scale * 1000 if v else None)

    traces = [{"type": "scatter", "mode": "lines", "name": f"全国 {label}",
               "x": xs, "y": ys, "line": CURVE_STYLE[label],
               "hovertemplate": f"全国{label}<br>%{{y:,.0f}}円<extra></extra>"}
              for label, ys in curves.items() if any(ys)]
    if xs:
        return traces, None
    return [], ("対応先なし" if im.MAPPING.get(industry, ("none", []))[0] == "none"
                else "統計なし")


@app.route("/api/scatter")
def api_scatter():
    year = int(request.args.get("year", DEFAULT_YEAR))
    industry = request.args.get("industry", "すべて")
    traces = company_points(subset(year=year, industry=industry))
    curves, reason = national_curves(year, industry)
    return jsonify({"traces": traces + curves, "no_curve_reason": reason})


PAGE_SIZE = 100
SORTABLE = {"year", "name", "code", "market", "ind33", "prefecture",
            "employees", "employees_group", "percentile",
            "age", "service_years", "entry_age", "salary",
            "ratio_to_national", "ratio_to_listed"}


def sorted_rows(rows, field, desc):
    have = [r for r in rows if r.get(field) is not None]
    have.sort(key=lambda r: r[field], reverse=desc)
    return have + [r for r in rows if r.get(field) is None]


@app.route("/api/table")
def api_table():
    a = request.args
    rows = ROWS
    if a.get("year"):
        rows = [r for r in rows if str(r["year"]) == a["year"]]
    for field in ("market", "ind33", "prefecture"):
        if a.get(field):
            rows = [r for r in rows if r.get(field) == a[field]]
    if a.get("q"):
        q = a["q"].strip()
        rows = [r for r in rows if q in (r["name"] or "") or q == r["code"]]
    for field, lo, hi in (("employees", "emp_min", "emp_max"),
                          ("employees_group", "grp_min", "grp_max"),
                          ("salary", "sal_min", "sal_max")):
        if a.get(lo):
            rows = [r for r in rows if (r.get(field) or 0) >= float(a[lo])]
        if a.get(hi):
            rows = [r for r in rows if (r.get(field) or 0) <= float(a[hi])]

    field = a.get("sort") if a.get("sort") in SORTABLE else "salary"
    desc = a.get("desc", "1") == "1"
    rows = sorted_rows(rows, field, desc)

    page = max(1, int(a.get("page", 1)))
    start = (page - 1) * PAGE_SIZE
    return jsonify({
        "total": len(rows), "page": page,
        "pages": max(1, -(-len(rows) // PAGE_SIZE)),
        "sort": field, "desc": desc,
        "rows": rows[start:start + PAGE_SIZE],
    })


@app.route("/api/summary")
def api_summary():
    out = []
    for year in YEARS:
        for market in ("プライム", "スタンダード", "グロース"):
            rows = subset(year=year, market=market)
            if len(rows) < 5:
                continue

            def med(key):
                v = [r[key] for r in rows if r[key]]
                return round(statistics.median(v), 3) if v else None

            out.append({
                "year": year, "market": market, "n": len(rows),
                "substituted": rows[0]["stats_substituted"],
                "salary_median": statistics.median(
                    [r["salary"] for r in rows]),
                "age_median": statistics.median([r["age"] for r in rows]),
                "ratio_to_national": med("ratio_to_national"),
                "ratio_to_listed": med("ratio_to_listed"),
            })
    return jsonify({"rows": out})


if __name__ == "__main__":
    print(f"企業 {len(ROWS):,} 件 / 対象年 {YEARS}")
    app.run(debug=True, port=5000)
