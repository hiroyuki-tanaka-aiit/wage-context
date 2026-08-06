# aiit-sp-kadai4

## Requirements

```sh
brew install uv
```

## Usage

```sh
uv run --with flask python3 app.py
```

http://127.0.0.1:5000/

## API keys

EDINET: https://disclosure2.edinet-fsa.go.jp/week0010.aspx
e-Stat — https://www.e-stat.go.jp

`~/.config/aiit/edinet.env`

```
EDINET_API_KEY=...
ESTAT_APP_ID=...
```

## Fetch data

```sh
uv run --with xlrd     python3 scripts/fetch_reference.py
uv run                 python3 scripts/collect_edinet.py --all-years
uv run                 python3 scripts/collect_estat.py
uv run --with openpyxl python3 scripts/collect_estat_files.py
uv run                 python3 scripts/analyze.py
```
