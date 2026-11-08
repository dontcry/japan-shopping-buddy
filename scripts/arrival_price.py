# -*- coding: utf-8 -*-
"""到手价试算：商品价 + 日本国内运费 + 转运运费 + 转运手续费 + 关税，全部换算为 CNY（估算）。

公式见 references/price_formula.md；转运价目见 references/forwarding_rates.md。

用法：
  python3 arrival_price.py --price-jpy 16500
  python3 arrival_price.py --price-jpy 16500 --channel echina --domestic-jpy 660
  python3 arrival_price.py --price-jpy 16500 --baseline   # 用内置基准汇率，不打网络
  python3 arrival_price.py --price-jpy 33000 --quote \
      --item-name "ace GENE CB2 背包 20025" --platform "乐天 / Amazon Japan" \
      --condition "全新" --confidence "高" --quote-file quote.md   # 直接产出确认单
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
        "provenance": {
            "computed_by": "scripts/arrival_price.py",
            "rate_by": "scripts/exchange_rate.py",
            "rule": "本结果所有金额均由脚本计算，模型不得自行推算或改写数值（provenance 约束）。",
        },
    }


FIXED_CAVEATS = [
    "成色说明为识别推断，非实际值，待核实",
    "二手/券后价为特定条件下价格，不等于常规价",
    "汇率有快照时效，成交前请刷新复查",
    "转运运费按实际称重浮动，本单为价目区间",
    "渠道覆盖有限：未覆盖的渠道可能存在更低报价",
]


def build_quote_md(res, item_name="", platform="", condition="", confidence="",
                   caveats=None, quote_type="purchase"):
    """把试算结果渲染成整张确认单 Markdown（金额全部来自脚本，模型只做转述）。"""
    b = res["breakdown_cny"]
    r = res["rate"]
    ch = res["channel"]
    title = "购买确认单（估算）" if quote_type == "purchase" else "支付确认单（估算）"
    lines = [f"# {title}", ""]

    if item_name:
        lines.append(f"**商品**：{item_name}")
    if platform:
        lines.append(f"**平台/渠道**：{platform}")
    if condition:
        lines.append(f"**成色**：{condition}（识别推断，标注待核实）")
    if confidence:
        lines.append(f"**同款匹配置信度**：{confidence}")
    lines.append("")

    lines += [
        f"**到手价明细（估算，汇率快照 {r['snapshot_time']}，JPY→CNY {r['jpy_cny']}，来源 {r['source']}）**",
        "",
        "| 分项 | 金额（CNY） |",
        "|---|---|",
        f"| 商品价（¥{res['item']['price_jpy']:,.0f}） | {b['item']:,.2f} |",
        f"| 日本国内运费（¥{res['item']['domestic_jpy']:,.0f}） | {b['domestic']:,.2f} |",
        f"| 转运运费（{ch['label']}，{ch['days']}） | {b['forwarding'][0]:,.2f} ~ {b['forwarding'][1]:,.2f} |",
        f"| 转运手续费 | {b['handling_fee'][0]:,.2f} ~ {b['handling_fee'][1]:,.2f} |",
        f"| 行邮税（20%） | {b['tariff_20pct']:,.2f} |",
        f"| **合计（估算）** | **{res['total_cny'][0]:,.2f} ~ {res['total_cny'][1]:,.2f}** |",
        "",
        "**Caveats（必读）**",
        "",
    ]
    for c in FIXED_CAVEATS + list(caveats or []):
        lines.append(f"- {c}")
    lines += [
        "",
        "**估算声明**：以上金额由 `scripts/arrival_price.py` 计算，汇率由 `scripts/exchange_rate.py` 获取；"
        "模型未参与任何数值计算。以实时汇率 / 转运价目 / 海关核定为准。",
        "",
        "- [ ] 用户确认商品与金额",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="日淘到手价试算（估算）")
    ap.add_argument("--price-jpy", type=float, required=True, help="商品价（含税，日元）")
    ap.add_argument("--domestic-jpy", type=float, default=0, help="日本国内运费（日元，默认 0）")
    ap.add_argument("--channel", default="ems", choices=list(FORWARDING))
    ap.add_argument("--rate", type=float, default=None, help="手动指定汇率 JPY→CNY")
    ap.add_argument("--baseline", action="store_true", help="用内置基准汇率，不打网络")
    ap.add_argument("--quote", action="store_true", help="同时输出整张确认单（Markdown）")
    ap.add_argument("--quote-file", default=None, help="确认单写入的文件路径（配合 --quote）")
    ap.add_argument("--quote-type", default="purchase", choices=["purchase", "payment"],
                    help="purchase=购买确认单（中立版）；payment=支付确认单（PayPal 版）")
    ap.add_argument("--item-name", default="", help="商品名（写入确认单）")
    ap.add_argument("--platform", default="", help="平台/渠道（写入确认单）")
    ap.add_argument("--condition", default="", help="成色（写入确认单）")
    ap.add_argument("--confidence", default="", help="同款匹配置信度：高/中/低")
    ap.add_argument("--caveats", action="append", default=[], help="追加 Caveats，可重复")
    args = ap.parse_args()

    try:
        result = estimate(args.price_jpy, channel=args.channel,
                          domestic_jpy=args.domestic_jpy, rate=args.rate,
                          refresh_rate=not args.baseline)
    except JsbError as e:
        print(json.dumps({"status": "error", "code": "BAD_INPUT", "error": str(e)},
                         ensure_ascii=False, indent=2))
        raise SystemExit(1)

    result["status"] = "current"
    if args.quote:
        result["quote_md"] = build_quote_md(
            result, item_name=args.item_name, platform=args.platform,
            condition=args.condition, confidence=args.confidence,
            caveats=args.caveats, quote_type=args.quote_type,
        )
        if args.quote_file:
            with open(args.quote_file, "w", encoding="utf-8") as f:
                f.write(result["quote_md"])
            result["quote_file"] = args.quote_file

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
