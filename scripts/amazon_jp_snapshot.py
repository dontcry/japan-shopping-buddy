#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amazon Japan 页面快照抓价（Skill 的第四条数据源，替代已放弃的 PA-API）。

为什么需要：日亚产品页直连会返回 HTTP 200 但只有 ~3.8KB 的反爬空壳（无标题无价格）。
本脚本用「本机代理 + 浏览器 UA + 英文 `/-/en/` 路径 + 目的站 Cookie」把完整页面（~370KB）取回来再解析。

用法：
  python3 amazon_jp_snapshot.py --asin B0G56GGKKK
  python3 amazon_jp_snapshot.py --url "https://www.amazon.co.jp/-/en/dp/B0G56GGKKK"
  python3 amazon_jp_snapshot.py --bestsellers toys --limit 5     # 随机/榜单找商品
  python3 amazon_jp_snapshot.py --asin B0GGRD4729 --no-proxy     # 不走代理

输出 JSON：status（current/empty/unavailable）+ code + 价格/标题/评分/榜单/库存。
"""
import argparse
import json
import re

from _common import JsbError, http_request, proxy_enabled

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    "Accept-Encoding": "identity",
    "Cache-Control": "no-cache",
    "Connection": "close",
    # 让日亚按日本站渲染（日元计价、日文/英文标题均可）
    "Cookie": "lc-acbjp=en_US; i18n-prefs=JPY; sp-cdn=\"L5Z9:JP\"",
}

ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")


def _text(html, pattern, group=1, flags=re.S):
    m = re.search(pattern, html, flags)
    if not m:
        return None
    return " ".join(m.group(group).split())


def parse_price(html):
    """只在「主购买区」范围内找价，绝不拿页面任意位置的 a-price 充数。

    日亚页面会混入大量推荐位/轮播价（实测同一页有 ¥2,021 / ¥3,313 / ¥8,716 等），
    若全局正则取第一个，会得到与商品无关的假价 —— 这正是 provenance 约束要防的事。
    """
    # 1) apex_desktop：主购买价所在区块（最可信）
    i = html.find('id="apex_desktop"')
    scope = html[i:i + 12000] if i > 0 else ""
    m = re.search(r'a-offscreen">\s*(?:¥|￥|JPY\s*)\s*([\d,]{3,})', scope)
    if m:
        return int(m.group(1).replace(",", "")), "apex_desktop"

    # 2) corePrice 区块
    block = re.search(r'id="corePrice[^"]*"(.*?)id="availability"', html, re.S)
    if block:
        m = re.search(r'a-offscreen">\s*(?:¥|￥|JPY\s*)\s*([\d,]{3,})', block.group(1))
        if m:
            return int(m.group(1).replace(",", "")), "core_price_block"

    # 3) 页面内嵌 JSON（部分站点变体会带）
    m = re.search(r'"priceAmount"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1)), "priceAmount_json"

    return None, None


def parse_item(html, asin):
    price, price_src = parse_price(html)
    return {
        "asin": asin,
        "title": _text(html, r'id="productTitle"[^>]*>(.*?)</span>'),
        "price_jpy": price,
        "price_source": price_src,
        "rating": _text(html, r'"ratingValue"\s*:\s*"?([0-9.]+)')
                  or _text(html, r'a-icon-alt">\s*([0-9.]+) out of 5'),
        "reviews": _text(html, r'"reviewCount"\s*:\s*(\d+)')
                   or _text(html, r'id="acrCustomerReviewText"[^>]*>([\d,]+)'),
        "availability": _text(html, r'id="availability".*?<span[^>]*>(.*?)</span>'),
        "best_seller_rank": _text(html, r'Best Sellers Rank.*?#([\d,]+) in ([^<(]+)', group=0),
        "seller": _text(html, r'id="sellerProfileTriggerId"[^>]*>(.*?)</a>'),
        "condition": "全新（日亚主购买价）",
        "url": f"https://www.amazon.co.jp/dp/{asin}/",
        "source": "amazon_jp_page_snapshot",
    }


def snapshot(asin, no_proxy=False):
    url = f"https://www.amazon.co.jp/-/en/dp/{asin}/"
    use_proxy = proxy_enabled() and not no_proxy
    try:
        status, html = http_request("GET", url, headers=HEADERS, use_proxy=use_proxy, timeout=25)
    except JsbError as e:
        return {"status": "unavailable", "code": "NET_UNREACHABLE", "asin": asin,
                "reason": str(e), "hint": "本机需 JSB_PROXY=1 启用代理；云端服务器默认直连即可"}

    if status != 200:
        return {"status": "unavailable", "code": "HTTP_ERROR", "asin": asin,
                "http_status": status, "reason": html[:120]}

    if len(html) < 50000:
        return {"status": "unavailable", "code": "ANTIBOT_SHELL", "asin": asin,
                "page_bytes": len(html),
                "reason": "命中反爬空壳页（<50KB），无有效商品信息",
                "hint": "确认代理可用、UA 与 /-/en/ 路径生效；或稍后重试"}

    item = parse_item(html, asin)
    item["status"] = "current" if item["price_jpy"] else "empty"
    item["code"] = None if item["price_jpy"] else "PRICE_MISSING"
    item["page_bytes"] = len(html)
    if not item["price_jpy"]:
        item["reason"] = ("页面已取回但主购买价由前端 JS 注入（服务端 HTML 为骨架），"
                          "HTTP 快照取不到价；请由 Agent 用浏览器渲染取价，或改由乐天 RWS 比价。"
                          "标题/评分/榜单等元信息仍可用。")
    return item


def bestsellers(category="toys", limit=5, no_proxy=False):
    """从日亚畅销榜抓若干 ASIN，用于随机抽样测试。"""
    url = f"https://www.amazon.co.jp/-/en/gp/bestsellers/{category}/"
    use_proxy = proxy_enabled() and not no_proxy
    try:
        status, html = http_request("GET", url, headers=HEADERS, use_proxy=use_proxy, timeout=25)
    except JsbError as e:
        return {"status": "unavailable", "code": "NET_UNREACHABLE", "reason": str(e)}
    if status != 200 or len(html) < 50000:
        return {"status": "unavailable", "code": "ANTIBOT_SHELL" if status == 200 else "HTTP_ERROR",
                "http_status": status, "page_bytes": len(html)}

    seen, out = set(), []
    for asin in ASIN_RE.findall(html):
        if asin in seen:
            continue
        seen.add(asin)
        out.append(asin)
        if len(out) >= limit:
            break
    return {"status": "current" if out else "empty", "category": category,
            "asins": out, "page_bytes": len(html)}


def main():
    ap = argparse.ArgumentParser(description="Amazon Japan 页面快照抓价")
    ap.add_argument("--asin")
    ap.add_argument("--url")
    ap.add_argument("--bestsellers", help="类目，如 toys / electronics / kitchen")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--no-proxy", action="store_true")
    args = ap.parse_args()

    if args.bestsellers:
        result = bestsellers(args.bestsellers, args.limit, args.no_proxy)
    else:
        asin = args.asin
        if not asin and args.url:
            m = ASIN_RE.search(args.url)
            asin = m.group(1) if m else None
        if not asin:
            print(json.dumps({"status": "error", "code": "BAD_INPUT",
                              "error": "需要 --asin / --url / --bestsellers 之一"},
                             ensure_ascii=False, indent=2))
            raise SystemExit(1)
        result = snapshot(asin, args.no_proxy)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
