# -*- coding: utf-8 -*-
"""到手价试算：商品价 + 日本国内运费 + 转运运费 + 转运手续费 + 关税，全部换算为 CNY（估算）。

公式见 references/price_formula.md；转运价目见 references/forwarding_rates.md。

用法：
  python3 arrival_price.py --price-jpy 16500
  python3 arrival_price.py --price-jpy 16500 --channel echina --domestic-jpy 660
  python3 arrival_price.py --price-jpy 16500 --baseline   # 用内置基准汇率，不打网络
"""
import argparse
import datetime
import json

import exchange_rate
from _common import JsbError

# 转运价目（转送JAPAN 中国区，JPY；脱敏自 azone 实测，标注估算）
FORWARDING = {
    "echina": {"label": "eCHINA", "range": (1500, 2600), "days": "约 1 周", "note": "最省"},
    "ems": {"label": "EMS", "range": (2200, 2800), "days": "3~7 天", "note": "最稳，保价规范"},
    "sf": {"label": "SF CHINA", "range": (2950, 3600), "days": "—", "note": "贵"},
    "ship": {"label": "船运", "range": (1800, 2200), "days": "1~2 月", "note": "慢"},
}
HANDLING_FEE = (300, 550)      # 转送手续费 JPY/件
TARIFF_RATE = 0.20             # 玩具/人偶 行邮税 20%
DEFAULT_RATE = 0.04224


def estimate(price_jpy, channel="ems", domestic_jpy=0.0, rate=None, refresh_rate=True):
    ch = FORWARDING.get(channel)
    if not ch:
        raise JsbError(f"未知转运线路：{channel}（可选 {', '.join(FORWARDING)}）")

    if rate is None:
        if refresh_rate:
            r = exchange_rate.fetch()  # 实时刷新，网络失败自动降级到内置基准
            rate, rate_source = r["rate"], r["source"]
        else:
            rate, rate_source = DEFAULT_RATE, "builtin_baseline"
    else:
        rate_source = "manual"

    price_jpy = float(price_jpy)
    domestic_jpy = float(domestic_jpy)
    item_cny = price_jpy * rate
    domestic_cny = domestic_jpy * rate
    ship_min, ship_max = ch["range"]
    ship_cny = (ship_min * rate, ship_max * rate)
    fee_cny = (HANDLING_FEE[0] * rate, HANDLING_FEE[1] * rate)
    tariff_cny = item_cny * TARIFF_RATE

    total_min = item_cny + domestic_cny + ship_cny[0] + fee_cny[0] + tariff_cny
    total_max = item_cny + domestic_cny + ship_cny[1] + fee_cny[1] + tariff_cny

    return {
        "item": {"price_jpy": price_jpy, "domestic_jpy": domestic_jpy},
        "channel": {"key": channel, "label": ch["label"], "days": ch["days"],
                    "note": ch["note"], "jp": list(ch["range"])},
        "rate": {"jpy_cny": round(rate, 6), "source": rate_source,
                 "snapshot_time": datetime.datetime.now().astimezone().isoformat()},
        "breakdown_cny": {
            "item": round(item_cny, 2),
            "domestic": round(domestic_cny, 2),
            "forwarding": (round(ship_cny[0], 2), round(ship_cny[1], 2)),
            "handling_fee": (round(fee_cny[0], 2), round(fee_cny[1], 2)),
            "tariff_20pct": round(tariff_cny, 2),
        },
        "total_cny": (round(total_min, 2), round(total_max, 2)),
        "estimate_note": "估算值：以实时汇率 / 转运价目 / 海关核定为准，成交前请刷新复查。",
    }


def main():
    ap = argparse.ArgumentParser(description="日淘到手价试算（估算）")
    ap.add_argument("--price-jpy", type=float, required=True, help="商品价（含税，日元）")
    ap.add_argument("--domestic-jpy", type=float, default=0, help="日本国内运费（日元，默认 0）")
    ap.add_argument("--channel", default="ems", choices=list(FORWARDING))
    ap.add_argument("--rate", type=float, default=None, help="手动指定汇率 JPY→CNY")
    ap.add_argument("--baseline", action="store_true", help="用内置基准汇率，不打网络")
    args = ap.parse_args()

    try:
        result = estimate(args.price_jpy, channel=args.channel,
                          domestic_jpy=args.domestic_jpy, rate=args.rate,
                          refresh_rate=not args.baseline)
    except JsbError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()