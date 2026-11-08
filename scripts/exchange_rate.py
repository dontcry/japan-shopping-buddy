# -*- coding: utf-8 -*-
"""汇率查询：JPY→CNY（可选任意目标币种，用于美国/欧盟免税额阈值换算）。

主源 open.er-api.com/v6（免 key）→ 备源 exchangerate-api.com/v4 → 本地缓存 → 内置基准（仅 CNY）。
用法：
  python3 exchange_rate.py
  python3 exchange_rate.py --to USD        # JPY→USD（美国 800 美元免税额换算）
  python3 exchange_rate.py --baseline      # 取内置基准，不打网络（仅 CNY）
"""
import argparse
import json
import os

from _common import http_request, JsbError

FALLBACK_RATE = 0.04224  # 实测基准（k780），仅 JPY→CNY

SOURCES = [
    ("open.er-api.com/v6", "https://open.er-api.com/v6/latest/JPY", "rates"),
    ("exchangerate-api.com/v4", "https://api.exchangerate-api.com/v4/latest/JPY", "rates"),
]


def _cache_file(target):
    base = os.environ.get("JSB_CACHE_DIR", os.path.expanduser("~/.japan-shopping-buddy"))
    return os.path.join(base, f"exchange_rate_{target}.json")


def _read_cache(target):
    try:
        with open(_cache_file(target), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(record, target):
    try:
        os.makedirs(os.path.dirname(_cache_file(target)), exist_ok=True)
        with open(_cache_file(target), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fetch(target="CNY"):
    """查询 JPY→target 汇率；网络异常时降级到缓存/内置基准，绝不抛异常。"""
    errors = []
    for source, url, rates_key in SOURCES:
        try:
            # 汇率 API 属全球 CDN，无需日本代理，直连即可
            status, text = http_request("GET", url, use_proxy=False, timeout=12)
            if status == 200:
                data = json.loads(text)
                rate = data.get(rates_key, {}).get(target)
                if rate:
                    return {
                        "base": "JPY",
                        "target": target,
                        "rate": float(rate),
                        "source": source,
                        "time_utc": data.get("time_last_update_utc") or data.get("date"),
                        "is_fallback": False,
                    }
            errors.append(f"{source} -> HTTP {status}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{source} -> {e}")

    cached = _read_cache(target)
    if cached and cached.get("rate"):
        cached["is_fallback"] = True
        cached["fallback_reason"] = "network_failed: " + "; ".join(errors)
        return cached

    if target == "CNY":
        return {
            "base": "JPY",
            "target": "CNY",
            "rate": FALLBACK_RATE,
            "source": "builtin_baseline",
            "is_fallback": True,
            "fallback_reason": "network_failed: " + "; ".join(errors),
        }
    # 非 CNY 无内置基准：返回空汇率，由调用方判定「阈值换算不可用」，不编数字
    return {
        "base": "JPY", "target": target, "rate": None,
        "source": "unavailable", "is_fallback": True,
        "fallback_reason": "network_failed: " + "; ".join(errors),
    }


def main():
    ap = argparse.ArgumentParser(description="查询 JPY→目标币种汇率")
    ap.add_argument("--to", default="CNY", help="目标币种（默认 CNY）")
    ap.add_argument("--baseline", action="store_true", help="仅返回内置基准（仅 CNY 可用）")
    args = ap.parse_args()

    if args.baseline:
        if args.to != "CNY":
            print(json.dumps({"error": "内置基准仅覆盖 JPY→CNY", "code": "NO_BASELINE"},
                             ensure_ascii=False, indent=2))
            raise SystemExit(1)
        result = {
            "base": "JPY", "target": "CNY", "rate": FALLBACK_RATE,
            "source": "builtin_baseline", "is_fallback": True,
        }
    else:
        try:
            result = fetch(args.to)
        except JsbError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        if not result.get("is_fallback") and result.get("rate"):
            _write_cache(result, args.to)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()