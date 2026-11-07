# -*- coding: utf-8 -*-
"""汇率查询：JPY→CNY。

主源 open.er-api.com/v6（免 key）→ 备源 exchangerate-api.com/v4 → 本地缓存 → 内置基准 0.04224。
用法：
  python3 exchange_rate.py
  python3 exchange_rate.py --baseline   # 直接取内置基准，不打网络
"""
import argparse
import json
import os

from _common import http_request, JsbError

FALLBACK_RATE = 0.04224  # 实测基准（k780）

SOURCES = [
    ("open.er-api.com/v6", "https://open.er-api.com/v6/latest/JPY", "rates"),
    ("exchangerate-api.com/v4", "https://api.exchangerate-api.com/v4/latest/JPY", "rates"),
]


def _cache_file():
    base = os.environ.get("JSB_CACHE_DIR", os.path.expanduser("~/.japan-shopping-buddy"))
    return os.path.join(base, "exchange_rate.json")


def _read_cache():
    try:
        with open(_cache_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(record):
    try:
        os.makedirs(os.path.dirname(_cache_file()), exist_ok=True)
        with open(_cache_file(), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fetch():
    """查询汇率；任何网络异常都降级到内置基准，绝不抛异常。"""
    errors = []
    for source, url, rates_key in SOURCES:
        try:
            status, text = http_request("GET", url, use_proxy=False, timeout=12)
            if status == 200:
                data = json.loads(text)
                rate = data.get(rates_key, {}).get("CNY")
                if rate:
                    return {
                        "base": "JPY",
                        "target": "CNY",
                        "rate": float(rate),
                        "source": source,
                        "time_utc": data.get("time_last_update_utc") or data.get("date"),
                        "is_fallback": False,
                    }
            errors.append(f"{source} -> HTTP {status}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{source} -> {e}")

    cached = _read_cache()
    if cached and cached.get("rate"):
        cached["is_fallback"] = True
        cached["fallback_reason"] = "network_failed: " + "; ".join(errors)
        return cached

    return {
        "base": "JPY",
        "target": "CNY",
        "rate": FALLBACK_RATE,
        "source": "builtin_baseline",
        "is_fallback": True,
        "fallback_reason": "network_failed: " + "; ".join(errors),
    }


def main():
    ap = argparse.ArgumentParser(description="查询 JPY→CNY 汇率")
    ap.add_argument("--baseline", action="store_true", help="仅返回内置基准，不打网络")
    args = ap.parse_args()

    if args.baseline:
        result = {
            "base": "JPY", "target": "CNY", "rate": FALLBACK_RATE,
            "source": "builtin_baseline", "is_fallback": True,
        }
    else:
        try:
            result = fetch()
        except JsbError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        if not result.get("is_fallback") and result.get("rate"):
            _write_cache(result)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
