import json
import pathlib
import urllib.request

import xlrd

from config import load_key

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
UA_API = "AIIT-SP-Kadai4/1.0 (student coursework)"
JPX_URL = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
           "tvdivq0000001vg2-att/data_j.xls")
ESTAT = "https://api.e-stat.go.jp/rest/3.0/app/json"


def fetch(url, ua=UA_API, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=timeout).read()


def cell_code(v):
    return str(int(v)) if isinstance(v, float) else str(v).strip()


def fetch_jpx():
    book = xlrd.open_workbook(file_contents=fetch(JPX_URL, UA_BROWSER))
    sheet = book.sheet_by_index(0)
    hdr = [sheet.cell_value(0, c) for c in range(sheet.ncols)]
    i_market, i_ind, i_code, i_name = (hdr.index("市場・商品区分"),
                                       hdr.index("33業種区分"),
                                       hdr.index("コード"), hdr.index("銘柄名"))
    rows = []
    for r in range(1, sheet.nrows):
        market = str(sheet.cell_value(r, i_market))
        if "内国株式" not in market:
            continue
        rows.append({"code": cell_code(sheet.cell_value(r, i_code)),
                     "name": str(sheet.cell_value(r, i_name)),
                     "market": market.replace("（内国株式）", ""),
                     "ind33": str(sheet.cell_value(r, i_ind))})
    (DATA / "jpx.json").write_text(json.dumps(rows, ensure_ascii=False),
                                   encoding="utf-8")
    alpha = sum(1 for x in rows if not x["code"].isdigit())
    print(f"jpx.json          {len(rows):,} 社（英字コード {alpha} 社）")


def fetch_estat_meta(app_id):
    tables = [("0003425913", "estat_codes.json"),
              ("0003425893", "estat_codes_age.json")]
    for sid, out in tables:
        url = f"{ESTAT}/getMetaInfo?appId={app_id}&statsDataId={sid}"
        d = json.loads(fetch(url))
        objs = d["GET_META_INFO"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"]
        codes = {}
        for o in objs:
            cls = o["CLASS"]
            cls = cls if isinstance(cls, list) else [cls]
            codes[o["@id"]] = {"name": o["@name"],
                               "values": {c["@name"]: c["@code"] for c in cls}}
        (DATA / out).write_text(
            json.dumps(codes, ensure_ascii=False, indent=1), encoding="utf-8")
        n = sum(len(v["values"]) for v in codes.values())
        print(f"{out:<18}{n:,} コード")
        if sid == "0003425913":
            ind = next(v for v in codes.values() if "産業" in v["name"])
            (DATA / "estat_ind.json").write_text(
                json.dumps([{"code": c, "name": n}
                            for n, c in ind["values"].items()],
                           ensure_ascii=False), encoding="utf-8")
            print(f"estat_ind.json    {len(ind['values'])} 産業分類")


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    fetch_jpx()
    fetch_estat_meta(load_key("ESTAT_APP_ID"))
