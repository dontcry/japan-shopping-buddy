# -*- coding: utf-8 -*-
"""冒烟回归：日淘搭子（华为·小红书赛版）离线可复测。

用法：
  python3 smoke_test.py            # 离线全量（不打网络，评委/CI 可直接跑）
  python3 smoke_test.py --online   # 追加联网用例（汇率刷新、Amazon 快照）

所有断言均为「脚本输出契约」，不涉及模型推断，可作参赛作品的复测证据。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BASE_RATE = 0.04224

PASS, FAIL = [], []


def run(script, *args):
    p = subprocess.run([PY, os.path.join(HERE, script), *args],
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout


def est(*args):
    code, out = run("arrival_price.py", *args)
    try:
        return code, json.loads(out)
    except json.JSONDecodeError:
        return code, {"_raw": out}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok  " if cond else "  FAIL") + f"  {name}" + (f"  [{detail}]" if detail and not cond else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true", help="追加联网用例")
    online = ap.parse_args().online

    print("[1] 汇率（离线基准）")
    code, r = run("exchange_rate.py", "--baseline")
    d = json.loads(r) if code == 0 and r.strip() else {}
    check("汇率 CLI 有输出（__main__ 入口存在）", bool(d), f"exit={code}")
    check("基准汇率 = 0.04224", d.get("rate") == BASE_RATE, str(d.get("rate")))
    check("基准来源标记 builtin_baseline", d.get("source") == "builtin_baseline")

    print("[2] 中国大陆行邮税")
    _, x = est("--price-jpy", "16500", "--channel", "ems", "--destination", "cn",
               "--tariff-category", "textile", "--baseline")
    item = 16500 * BASE_RATE
    check("商品价折算", x["breakdown_cny"]["item"] == round(item, 2), str(x["breakdown_cny"]["item"]))
    check("纺织品税率 20%", x["tariff"]["rate"] == 0.2)
    check("行邮税 = 货值×20%", x["tariff"]["charged_cny"] == round(item * 0.2, 2), str(x["tariff"]["charged_cny"]))
    check("未触发免征", x["tariff"]["exempt"] is False)

    _, x = est("--price-jpy", "3520", "--destination", "cn", "--tariff-category", "it", "--baseline")
    check("小额应征 <50 元自动免征", x["tariff"]["exempt"] is True and x["tariff"]["charged_cny"] == 0,
          f"raw={x['tariff']['raw_cny']}")

    _, x = est("--price-jpy", "980000", "--destination", "cn", "--tariff-category", "it", "--baseline")
    check("¥980,000 相机 13% 税正确", x["tariff"]["charged_cny"] == 5381.38, str(x["tariff"]["charged_cny"]))
    check("超 1000 元个人邮递限值告警", x.get("postal_limit", {}).get("exceeded") is True)

    _, x = est("--price-jpy", "16500", "--destination", "cn", "--baseline")
    check("未指定品类按税目2 其他商品 20% 兜底", x["tariff"]["rate"] == 0.2 and x["tariff"]["source"] == "default")

    print("[3] 收货地三档（本版不含海外税制）")
    _, x = est("--price-jpy", "16500", "--destination", "hk", "--baseline")
    check("HK 自由港 0 税", x["tariff"]["charged_cny"] == 0.0 and x["tariff"]["modeled"] is True)
    _, x = est("--price-jpy", "16500", "--destination", "other", "--baseline")
    check("other 未建模且不编税", x["tariff"]["modeled"] is False and x["tariff"]["charged_cny"] == 0.0)

    print("[4] 转运与重量")
    for ch, lo, hi in (("echina", 1500, 2600), ("ems", 2200, 2800), ("sf", 2950, 3600), ("ship", 1800, 2200)):
        _, x = est("--price-jpy", "16500", "--channel", ch, "--baseline")
        check(f"{ch} 价目区间 {lo}~{hi}", x["channel"]["jp"] == [lo, hi], str(x["channel"]["jp"]))
    _, x = est("--price-jpy", "16500", "--weight-kg", "6", "--baseline")
    check("超 1.5kg 触发重物警告", "weight_warning" in x)
    _, x = est("--price-jpy", "16500", "--weight-kg", "1.5", "--baseline")
    check("1.5kg 边界不误报", "weight_warning" not in x)

    print("[5] 输入校验")
    for args, name in (
        (["--price-jpy", "0", "--baseline"], "价格 0 拒绝"),
        (["--price-jpy", "-100", "--baseline"], "负价拒绝"),
    ):
        code, x = est(*args)
        check(name, code != 0 and x.get("code") == "BAD_INPUT", f"exit={code} code={x.get('code')}")
    # argparse 层拦截（退出码 2，走 usage 而非 JSON）
    for args, name in (
        (["--price-jpy", "16500", "--tariff-category", "xxx", "--baseline"], "未知税目拒绝"),
        (["--price-jpy", "16500", "--channel", "xxx", "--baseline"], "未知渠道拒绝"),
        (["--price-jpy", "16500", "--destination", "us", "--baseline"], "us 目的地拒绝"),
        (["--price-jpy", "16500", "--destination", "eu", "--baseline"], "eu 目的地拒绝"),
    ):
        code, _ = est(*args)
        check(name, code == 2, f"exit={code}")

    print("[6] 确认单渲染")
    qf = "/tmp/_smoke_huawei_quote.md"
    _, x = est("--price-jpy", "16500", "--destination", "cn", "--tariff-category", "textile",
               "--quote", "--quote-file", qf, "--item-name", "テスト「限定」/ 100% 手作り",
               "--condition", "全新", "--confidence", "高", "--caveats", "追加提示", "--baseline")
    md = open(qf, encoding="utf-8").read() if os.path.exists(qf) else ""
    check("确认单标题为购买确认单", md.startswith("# 购买确认单"))
    for kw in ("计算依据与数据来源", "估算声明", "用户确认商品与金额", "Caveats（必读）"):
        check(f"确认单含「{kw}」", kw in md)
    check("固定 Caveats 5 条齐全", all(s in md for s in [
        "成色说明为识别推断", "二手/券后价", "汇率有快照时效", "按实际称重浮动", "渠道覆盖有限"]))
    check("追加 Caveat 已合并", "追加提示" in md)
    check("特殊字符商品名无损", "テスト「限定」/ 100% 手作り" in md)
    check("JSON 契约字段齐全", all(k in x for k in (
        "breakdown_cny", "channel", "data_sources", "destination", "estimate_note",
        "item", "provenance", "rate", "status", "tariff", "total_cny")))

    print("[7] 税目矩阵（官方三档）")
    expect = {"it": .13, "food": .13, "precious_metal": .13, "furniture": .13, "toy": .13, "sports": .13,
              "textile": .2, "appliance": .2, "bike": .2, "other": .2,
              "tobacco_alcohol": .5, "jewelry": .5, "golf": .5, "luxury": .5}
    ok = True
    for cat, r in expect.items():
        _, x = est("--price-jpy", "100000", "--destination", "cn", "--tariff-category", cat, "--baseline")
        ok = ok and x["tariff"]["rate"] == r
    check("14 档税目税率全部正确", ok)

    if online:
        print("[8] 联网用例")
        code, r = run("exchange_rate.py")
        d = json.loads(r) if code == 0 else {}
        check("在线汇率可用且非降级", bool(d.get("rate")) and d.get("is_fallback") is False, str(d.get("source")))

    print()
    print(f"结果：{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("失败项：" + "; ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
