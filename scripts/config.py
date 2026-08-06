import os
import pathlib
import sys

CONFIG_DIR = pathlib.Path.home() / ".config" / "aiit"
ENV_FILES = ("kadai4.env", "edinet.env")


def load_key(name):
    if os.environ.get(name):
        return os.environ[name]
    for fn in ENV_FILES:
        p = CONFIG_DIR / fn
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    sys.exit(f"{name} が見つかりません（{CONFIG_DIR}/ に置いてください）")
