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
DEFAULT_RATE = 0.04224

# 行邮税按《中华人民共和国进境物品进口税税率表》（税目 1/2/3 = 13%/20%/50%）
TARIFF_PRESETS = {
    # 税目 1 — 13%
    "it": {"label": "书报/教育影视、计算机/手机/数码相机等信息技术产品", "rate": 0.13},
    "food": {"label": "食品/饮料/药品", "rate": 0.13},
    "precious_metal": {"label": "金银及其制品", "rate": 0.13},
    "furniture": {"label": "家具", "rate": 0.13},
    "toy": {"label": "玩具/游戏品/节日或其他娱乐用品", "rate": 0.13},
    "sports": {"label": "运动用品（不含高尔夫球及球具）/钓鱼用品", "rate": 0.13},
    # 税目 2 — 20%
    "textile": {"label": "纺织品及其制成品（服装/鞋帽/箱包）", "rate": 0.20},
    "appliance": {"label": "电视摄像机及其他电器用具（家电）", "rate": 0.20},
    "bike": {"label": "自行车", "rate": 0.20},
    "other": {"label": "税目 1/3 未包含的其他商品（普通化妆品/洗护等）", "rate": 0.20},
    # 税目 3 — 50%
    "tobacco_alcohol": {"label": "烟/酒", "rate": 0.50},
    "jewelry": {"label": "贵重首饰及珠宝玉石", "rate": 0.50},
    "golf": {"label": "高尔夫球及球具", "rate": 0.50},
    "luxury": {"label": "高档手表/高档化妆品", "rate": 0.50},
}
DEFAULT_TARIFF_RATE = 0.20     # 未指定品类时按税目 2「其他商品」兜底
TARIFF_EXEMPT_THRESHOLD = 50.0  # 应征税额 ≤50 元人民币免征（个人邮递物品）
POSTAL_LIMIT_CNY = 1000.0      # 个人邮递物品单次限值 1000 元（港澳台 800 元）

# 收货地（目的地）规则：CN 完整建模；HK/其他仅给框架并声明未建模，不编数字
DESTINATIONS = {
    "cn": {
        "label": "中国大陆", "tax_model": "personal_postal", "limit_cny": POSTAL_LIMIT_CNY,
        "basis": "行邮税按《中华人民共和国进境物品进口税税率表》税目 1/2/3（13%/20%/50%，2019-04-09 起）；"
                 "应征税额 ≤50 元免征、单次限值 1000 元（港澳台 800 元）出自《海关总署公告 2010 年第 43 号》",
    },
    "hk": {
        "label": "中国香港", "tax_model": "free_port", "limit_cny": None,
        "basis": "香港为自由港：一般商品不征进口关税与增值税（烟、酒、燃油等应课税品除外）",
    },
    "other": {
        "label": "其他目的地", "tax_model": "not_modeled", "limit_cny": None,
        "basis": "目的地进口税未建模，需按当地海关规定另计（如英国 £135、日本关税、加拿大 GST/PST 等）",
    },
}


def estimate(price_jpy, channel="ems", domestic_jpy=0.0, rate=None, refresh_rate=True,
             tariff_category=None, tariff_rate=None, destination="cn"):
    if price_jpy <= 0:
        raise JsbError(f"price_jpy 必须为正数（当前 {price_jpy}）")
    if domestic_jpy < 0:
        raise JsbError(f"domestic_jpy 不能为负（当前 {domestic_jpy}）")
    ch = FORWARDING.get(channel)
    if not ch:
        raise JsbError(f"未知转运线路：{channel}（可选 {', '.join(FORWARDING)}）")
    if destination not in DESTINATIONS:
        raise JsbError(f"未知收货地：{destination}（可选 {', '.join(DESTINATIONS)}）")
    if tariff_rate is not None and not 0 <= tariff_rate <= 1:
        raise JsbError(f"tariff_rate 必须在 0~1 之间（当前 {tariff_rate}）")
    if tariff_category and tariff_category not in TARIFF_PRESETS:
        raise JsbError(f"未知行邮税品类：{tariff_category}"
                       f"（可选 {', '.join(TARIFF_PRESETS)}）")

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

    dest = DESTINATIONS[destination]

    # 进口税：CN 完整建模；HK 自由港 0 税；其他目的地不建模（不编数字）
    if destination == "cn":
        if tariff_rate is not None:
            tr, tr_source, tr_label = float(tariff_rate), "manual", "手动指定"
        elif tariff_category:
            preset = TARIFF_PRESETS[tariff_category]
            tr, tr_source, tr_label = preset["rate"], tariff_category, preset["label"]
        else:
            tr, tr_source, tr_label = DEFAULT_TARIFF_RATE, "default", "未指定品类（按税目2其他商品兜底）"
        tariff_raw = item_cny * tr
        tariff_exempt = tariff_raw <= TARIFF_EXEMPT_THRESHOLD
        tariff_cny = 0.0 if tariff_exempt else tariff_raw
        tax_modeled = True
    elif destination == "hk":
        tr, tr_source, tr_label = 0.0, "destination_hk", "香港自由港（一般商品零关税、无增值税）"
        tariff_raw = tariff_cny = 0.0
        tariff_exempt = False
        tax_modeled = True
    else:
        tr, tr_source, tr_label = 0.0, "destination_other", "目的地进口税未建模"
        tariff_raw = tariff_cny = 0.0
        tariff_exempt = False
        tax_modeled = False

    total_min = item_cny + domestic_cny + ship_cny[0] + fee_cny[0] + tariff_cny
    total_max = item_cny + domestic_cny + ship_cny[1] + fee_cny[1] + tariff_cny
    snapshot = datetime.datetime.now().astimezone().isoformat()

    data_sources = [
        {"field": "商品价", "source": "用户提供的平台页面/截图（模型识别，非脚本抓取）"},
        {"field": "汇率", "source": f"scripts/exchange_rate.py（source={rate_source}，快照 {snapshot}）"},
        {"field": "转运运费/手续费", "source": "references/forwarding_rates.md（转送JAPAN 中国区价目区间，估算）"},
        {"field": "商品行情", "source": "scripts/rakuten_search.py（乐天 RWS）/ scripts/amazon_jp_snapshot.py（Amazon JP 快照），"
                                     "仅 status=current 的报价可引用"},
        {"field": "进口税", "source": (f"{dest['basis']}；本单适用：{tr_label}" if tax_modeled else dest["basis"])},
    ]

    return {
        "item": {"price_jpy": price_jpy, "domestic_jpy": domestic_jpy},
        "channel": {"key": channel, "label": ch["label"], "days": ch["days"],
                    "note": ch["note"], "jp": list(ch["range"])},
        "destination": {"key": destination, "label": dest["label"],
                        "tax_model": dest["tax_model"], "tax_modeled": tax_modeled,
                        "limit_cny": dest.get("limit_cny"),
                        "threshold_local": dest.get("threshold_local"),
                        "currency": dest.get("currency"), "basis": dest["basis"]},
        "rate": {"jpy_cny": round(rate, 6), "source": rate_source, "snapshot_time": snapshot},
        "tariff": {"rate": tr, "source": tr_source, "category": tr_label,
                   "raw_cny": round(tariff_raw, 2), "exempt": tariff_exempt,
                   "charged_cny": round(tariff_cny, 2),
                   "exempt_threshold": TARIFF_EXEMPT_THRESHOLD, "modeled": tax_modeled},
        "breakdown_cny": {
            "item": round(item_cny, 2),
            "domestic": round(domestic_cny, 2),
            "forwarding": (round(ship_cny[0], 2), round(ship_cny[1], 2)),
            "handling_fee": (round(fee_cny[0], 2), round(fee_cny[1], 2)),
            "tariff": round(tariff_cny, 2),
        },
        "total_cny": (round(total_min, 2), round(total_max, 2)),
        "data_sources": data_sources,
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
    t = res["tariff"]
    dest = res["destination"]
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
    lines.append(f"**收货地**：{dest['label']}（税制模型：{dest['tax_model']}）")
    lines.append("")

    if dest["key"] == "cn":
        if t["exempt"]:
            tax_cell = f"{t['rate']:.0%}｜{t['category']}"
            tax_extra = f"（应征 {t['raw_cny']:,.2f} ≤ {t['exempt_threshold']:.0f} 元，免征）"
        else:
            tax_cell = f"{t['rate']:.0%}｜{t['category']}"
            tax_extra = ""
        tax_label = "行邮税"
    elif dest["key"] == "hk":
        tax_cell, tax_extra, tax_label = "0%（香港自由港）", "", "进口税"
    else:
        tax_cell, tax_extra, tax_label = "未建模", "（需按目的地税法另计）", "进口税"

    lines += [
        f"**到手价明细（估算，汇率快照 {r['snapshot_time']}，JPY→CNY {r['jpy_cny']}，来源 {r['source']}）**",
        "",
        "| 分项 | 金额（CNY） |",
        "|---|---|",
        f"| 商品价（¥{res['item']['price_jpy']:,.0f}） | {b['item']:,.2f} |",
        f"| 日本国内运费（¥{res['item']['domestic_jpy']:,.0f}） | {b['domestic']:,.2f} |",
        f"| 转运运费（{ch['label']}，{ch['days']}） | {b['forwarding'][0]:,.2f} ~ {b['forwarding'][1]:,.2f} |",
        f"| 转运手续费 | {b['handling_fee'][0]:,.2f} ~ {b['handling_fee'][1]:,.2f} |",
        f"| {tax_label}（{tax_cell}） | {b['tariff']:,.2f}{tax_extra} |",
        f"| **合计（估算）** | **{res['total_cny'][0]:,.2f} ~ {res['total_cny'][1]:,.2f}** |",
        "",
        "**Caveats（必读）**",
        "",
    ]
    for c in FIXED_CAVEATS + list(caveats or []):
        lines.append(f"- {c}")

    lines += [
        "",
        "**计算依据与数据来源**",
        "",
        "| 分项 | 依据 / 来源 |",
        "|---|---|",
    ]
    for s in res["data_sources"]:
        lines.append(f"| {s['field']} | {s['source']} |")
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
    ap.add_argument("--weight-kg", type=float, default=None,
                    help="申报重量（kg）。内置价目表仅覆盖 ≤1.5kg 小件，超重会给出警告")
    ap.add_argument("--tariff-category", default=None, choices=list(TARIFF_PRESETS),
                    help="按官方税目取税率（it/toy/furniture/sports/food/precious_metal=13%%，"
                         "textile/appliance/bike/other=20%%，luxury/jewelry/golf/tobacco_alcohol=50%%）")
    ap.add_argument("--tariff-rate", type=float, default=None,
                    help="手动指定行邮税率（0~1，覆盖品类预设；仅 --destination cn 生效）")
    ap.add_argument("--destination", default="cn", choices=list(DESTINATIONS),
                    help="收货地：cn=中国大陆（完整行邮税建模）/ hk=香港自由港 / other=其他目的地（税未建模）")
    args = ap.parse_args()

    try:
        result = estimate(args.price_jpy, channel=args.channel,
                          domestic_jpy=args.domestic_jpy, rate=args.rate,
                          refresh_rate=not args.baseline,
                          tariff_category=args.tariff_category,
                          tariff_rate=args.tariff_rate,
                          destination=args.destination)
    except JsbError as e:
        print(json.dumps({"status": "error", "code": "BAD_INPUT", "error": str(e)},
                         ensure_ascii=False, indent=2))
        raise SystemExit(1)

    result["status"] = "current"
    if args.weight_kg is not None:
        result["weight_kg"] = args.weight_kg
        if args.weight_kg > 1.5:
            result["weight_warning"] = (
                f"申报重量 {args.weight_kg}kg 超出内置价目表适用范围（≤1.5kg 小件）："
                "下方转运费区间仅按小件价目估算，重物（家电/家具等）请以转送JAPAN 官网实时报价为准。")
            args.caveats.append(result["weight_warning"])
    item_cny = result["breakdown_cny"]["item"]
    if args.destination == "cn" and item_cny > POSTAL_LIMIT_CNY:
        result["postal_limit"] = {"item_cny": item_cny, "limit_cny": POSTAL_LIMIT_CNY,
                                  "exceeded": True}
        args.caveats.append(
            f"商品价折合 {item_cny:,.2f} 元，超过个人邮递物品单次限值 {POSTAL_LIMIT_CNY:,.0f} 元"
            "（港澳台 800 元）：本单不能直接按个人邮寄清关，需拆单、退运，或改走跨境电商零售进口"
            "（单次 5000 元限额、综合税率约 9.1%）/ 按货物报关。下方行邮税仅作参考。")
    if args.destination != "cn":
        args.caveats.append(
            "转运价目取自转送JAPAN 中国区价目，其他目的地的可用线路与运费可能不同；"
            "进口税未建模的，请按收货地海关规定另计。")
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
