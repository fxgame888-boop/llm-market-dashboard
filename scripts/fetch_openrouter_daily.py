# -*- coding: utf-8 -*-
"""
Fetch OpenRouter official daily usage:
  GET https://openrouter.ai/api/v1/datasets/rankings-daily
  Auth: environment variable OPENROUTER_API_KEY only

Writes (under this scripts/ directory):
  openrouter_api_daily_models.csv  - model-level (date, model, tokens)
  openrouter_usage_daily.csv       - provider aggregates (billion tokens / day) for dashboard

Usage:
  python fetch_openrouter_daily.py
  python fetch_openrouter_daily.py --start 2025-12-01 --end 2026-08-09
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DIR = Path(__file__).resolve().parent
BACKUP = DIR / "Backup"
MODELS_CSV = DIR / "openrouter_api_daily_models.csv"
USAGE_CSV = DIR / "openrouter_usage_daily.csv"
META_JSON = DIR / "openrouter_api_meta.json"
RAW_DIR = DIR / "openrouter_api_raw"
# Public CI: key only from env (never hardcode local secret paths in this repo).
API = "https://openrouter.ai/api/v1/datasets/rankings-daily"
# 1e9 tokens = 1 billion (matches MacroMicro unit "b")
TOKENS_PER_B = 1_000_000_000.0

# slug prefix -> dashboard provider name
PROVIDER_MAP = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "deepseek": "DeepSeek",
    "x-ai": "xAI",
    "xai": "xAI",
    "qwen": "Qwen",
    "alibaba": "Qwen",
    "mistralai": "Mistral",
    "mistral": "Mistral",
    "moonshotai": "Moonshot",
    "moonshot": "Moonshot",
    "minimax": "Minimax",
    "z-ai": "Zhipu",
    "zhipu": "Zhipu",
    "thudm": "Zhipu",
    "arcee-ai": "Arcee",
    "arcee": "Arcee",
    "meta-llama": "Meta",
    "meta": "Meta",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "nvidia": "Nvidia",
    "microsoft": "Microsoft",
    "amazon": "Amazon",
    "ai21": "AI21",
    "inflection": "Inflection",
    "01-ai": "01AI",
    "tencent": "Tencent",
    "xiaomi": "Xiaomi",
    "bytedance": "ByteDance",
    "nousresearch": "Nous",
    "openrouter": "OpenRouter",
    "other": "Other",
}


def load_api_key() -> str:
    env = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if env:
        return env
    raise RuntimeError(
        "OPENROUTER_API_KEY is not set. Export it in the environment "
        "(GitHub Actions secret or local shell)."
    )



def provider_of(permaslug: str) -> str:
    slug = (permaslug or "").strip().lower()
    if slug == "other":
        return "Other"
    if "/" in slug:
        prefix = slug.split("/", 1)[0]
    else:
        prefix = slug
    return PROVIDER_MAP.get(prefix, prefix[:1].upper() + prefix[1:] if prefix else "Other")


def daterange_chunks(start: date, end: date, chunk_days: int = 30):
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def http_get_json(url: str, key: str, retries: int = 4) -> dict:
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "CyndiResearch/1.0 (personal market dashboard)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            last_err = e
            if e.code in (429, 500, 502, 503):
                time.sleep(2 ** attempt + 1)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"request failed: {last_err}")


def fetch_window(key: str, start: date, end: date, period: str = "day") -> dict:
    q = urllib.parse.urlencode(
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "period": period,
        }
    )
    url = API + "?" + q
    return http_get_json(url, key)


def backup(path: Path) -> None:
    if not path.exists():
        return
    BACKUP.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, BACKUP / f"{path.stem}-{ts}{path.suffix}")


def aggregate(rows: list[dict]) -> tuple[list[dict], list[str], list[dict]]:
    """Return model rows sorted, provider list, provider daily rows."""
    # model level clean
    model_rows = []
    by_date_prov: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_date_total: dict[str, float] = defaultdict(float)

    for r in rows:
        d = r["date"]
        slug = r["model_permaslug"]
        tok = float(r["total_tokens"])
        model_rows.append({"date": d, "model": slug, "total_tokens": int(tok), "provider": provider_of(slug)})
        prov = provider_of(slug)
        by_date_prov[d][prov] += tok
        by_date_total[d] += tok

    # collect providers ordered by total desc then name
    totals = defaultdict(float)
    for d, m in by_date_prov.items():
        for p, v in m.items():
            totals[p] += v
    providers = sorted(totals.keys(), key=lambda p: (-totals[p], p))

    usage_rows = []
    for d in sorted(by_date_total.keys()):
        row = {"date": d, "Total": by_date_total[d] / TOKENS_PER_B}
        for p in providers:
            row[p] = by_date_prov[d].get(p, 0.0) / TOKENS_PER_B
        usage_rows.append(row)

    model_rows.sort(key=lambda x: (x["date"], -x["total_tokens"]))
    return model_rows, providers, usage_rows


def save_models(rows: list[dict]) -> None:
    with MODELS_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "model", "provider", "total_tokens"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def save_usage(rows: list[dict], providers: list[str]) -> None:
    # keep known order preference then rest
    preferred = [
        "DeepSeek",
        "OpenAI",
        "Anthropic",
        "Google",
        "Zhipu",
        "Qwen",
        "Minimax",
        "Moonshot",
        "Mistral",
        "xAI",
        "Tencent",
        "Xiaomi",
        "Meta",
        "Nvidia",
        "Other",
    ]
    ordered = [p for p in preferred if p in providers]
    for p in providers:
        if p not in ordered:
            ordered.append(p)
    fields = ["date", "Total"] + ordered
    with USAGE_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            out = {"date": r["date"], "Total": f"{float(r['Total']):.4f}"}
            for p in ordered:
                out[p] = f"{float(r.get(p) or 0):.4f}"
            w.writerow(out)
    return ordered


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-12-01", help="YYYY-MM-DD")
    ap.add_argument("--end", default="", help="YYYY-MM-DD default=yesterday UTC")
    ap.add_argument("--chunk", type=int, default=30, help="days per API request")
    args = ap.parse_args()

    key = load_api_key()
    print("KEY_OK len=%d" % len(key))

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        end = datetime.utcnow().date() - timedelta(days=1)

    print("range", start, "->", end)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    metas = []
    for a, b in daterange_chunks(start, end, args.chunk):
        print("fetch", a, b, "...")
        payload = fetch_window(key, a, b, "day")
        raw_path = RAW_DIR / f"rankings-daily_{a}_{b}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        rows = payload.get("data") or []
        meta = payload.get("meta") or {}
        metas.append(meta)
        print("  rows", len(rows), "meta", meta)
        all_rows.extend(rows)
        time.sleep(0.35)

    # de-dupe by (date, model)
    uniq = {}
    for r in all_rows:
        uniq[(r["date"], r["model_permaslug"])] = r
    all_rows = list(uniq.values())
    print("unique rows", len(all_rows))

    model_rows, providers, usage_rows = aggregate(all_rows)
    backup(MODELS_CSV)
    backup(USAGE_CSV)
    save_models(model_rows)
    ordered = save_usage(usage_rows, providers)

    last = usage_rows[-1] if usage_rows else None
    meta_out = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": API,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "n_model_rows": len(model_rows),
        "n_days": len(usage_rows),
        "providers": ordered if usage_rows else providers,
        "last_day": last["date"] if last else None,
        "last_total_b": round(float(last["Total"]), 4) if last else None,
        "unit": "billion tokens / day (total_tokens / 1e9)",
        "api_metas": metas,
        "citation": "Source: OpenRouter (openrouter.ai/rankings)",
    }
    META_JSON.write_text(json.dumps(meta_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "PASS days=%d last=%s total_b=%.2f models_csv=%s usage_csv=%s"
        % (
            len(usage_rows),
            last["date"] if last else None,
            float(last["Total"]) if last else 0,
            MODELS_CSV.name,
            USAGE_CSV.name,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("FAIL", type(e).__name__, e)
        sys.exit(1)
