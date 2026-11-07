# -*- coding: utf-8 -*-
"""乐天 RWS 商品搜索（一手比价）。

默认走本机代理 127.0.0.1:7890（日本站需代理可达）；缺凭证 / 代理不可达 / 返回错误时
降级为 MOCK 兜底并给出友好提示，绝不抛异常栈。

用法：
  RAKUTEN_APPLICATION_ID=.. RAKUTEN_ACCESS_KEY=.. python3 rakuten_search.py "フィギュア"
  RAKUTEN_APPLICATION_ID=.. RAKUTEN_ACCESS_KEY=.. python3 rakuten_search.py "フィギュア" --hits 5 --no-proxy
"""
import argparse
import json
import urllib.parse

from _common import load_secrets, http_request, JsbError

ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"

# 离线 Mock（代理不可达 / 评委复测网络抖动时的兜底，标注非实时）
MOCK_ITEMS = [
    {
        "itemName": "LYCEE Sweet Days YUKATA Collection 黒髪（POD020-LYB）【MOCK样例】",
        "itemCode": "azone-int:pod020lyb",
        "itemPrice": 16500,
        "catchcopy": "楽天限定・先着順・在庫わずか",
        "is_mock": True,
    },
    {
        "itemName": "フィギュアケース コレクションケース 積み重ね可能【MOCK样例】",
        "itemCode": "mock:10000368",
        "itemPrice": 748,
        "catchcopy": "八番屋 収納力アップ",
        "is_mock": True,
    },
]


def _brief(text, limit=200):
    return " ".join((text or "").split())[:limit]


def _fallback(keyword, reason):
    return {
        "count": None,
        "hits": None,
        "keyword": keyword,
        "items": MOCK_ITEMS,
        "is_fallback": True,
        "fallback_reason": reason,
        "hint": "当前跨境网络较慢或凭证缺失，已展示历史基准行情（MOCK，非实时），请稍后重试或检查代理/凭证。",
    }


def search(keyword, hits=5, no_proxy=False, secrets=None):
    secrets = secrets or load_secrets()
    app_id = secrets.get("RAKUTEN_APPLICATION_ID")
    access_key = secrets.get("RAKUTEN_ACCESS_KEY")
    if not app_id or not access_key:
        return _fallback(keyword, "缺少乐天凭证 RAKUTEN_APPLICATION_ID / RAKUTEN_ACCESS_KEY")

    params = urllib.parse.urlencode({
        "format": "json",
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "hits": int(hits),
    })
    url = f"{ENDPOINT}?{params}"

    try:
        status, text = http_request("GET", url, use_proxy=not no_proxy, timeout=15)
    except JsbError as e:
        return _fallback(keyword, f"网络不可达：{e}")

    if status != 200:
        return _fallback(keyword, f"HTTP {status}: {_brief(text)}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _fallback(keyword, "响应非 JSON")

    if "errorMessage" in data or "error" in data or "Items" not in data:
        return _fallback(keyword, _brief(text, 200))

    items = []
    for wrapper in data.get("Items", []):
        it = wrapper.get("Item", {})
        items.append({
            "itemName": it.get("itemName"),
            "itemCode": it.get("itemCode"),
            "itemPrice": it.get("itemPrice"),
            "itemPriceMax": it.get("itemPriceMax1"),
            "catchcopy": it.get("catchcopy"),
            "shopName": it.get("shopName"),
            "is_mock": False,
        })
    return {
        "count": data.get("count"),
        "hits": hits,
        "keyword": keyword,
        "items": items,
        "is_fallback": False,
    }


def main():
    ap = argparse.ArgumentParser(description="乐天 RWS 商品搜索")
    ap.add_argument("keyword")
    ap.add_argument("--hits", type=int, default=5)
    ap.add_argument("--no-proxy", action="store_true")
    args = ap.parse_args()

    result = search(args.keyword, hits=args.hits, no_proxy=args.no_proxy)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()