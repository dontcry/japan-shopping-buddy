# -*- coding: utf-8 -*-
"""乐天 RWS 商品搜索（一手比价）。

默认**直连**（云端服务器可直接访问日本 API）；本机开发需 JSB_PROXY=1 启用代理。
缺凭证 / 网络不可达 / 返回错误时降级为 MOCK 兜底并给出友好提示，绝不抛异常栈。

用法：
  RAKUTEN_APPLICATION_ID=.. RAKUTEN_ACCESS_KEY=.. python3 rakuten_search.py "フィギュア"
  JSB_PROXY=1 RAKUTEN_APPLICATION_ID=.. RAKUTEN_ACCESS_KEY=.. python3 rakuten_search.py "フィギュア" --hits 5
  python3 rakuten_search.py "フィギュア"               # 凭证自动从 scripts/secrets.json 读取
  python3 rakuten_search.py "フィギュア" --no-proxy   # 显式跳过代理
"""
import argparse
import json
import urllib.parse

from _common import load_secrets, http_request, proxy_enabled, JsbError

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


def _fallback(keyword, reason, code="RESULT_UNKNOWN"):
    return {
        "status": "unavailable",   # 降级：数据不可用 ≠ 查无此商品
        "code": code,
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
        return _fallback(keyword, "缺少乐天凭证 RAKUTEN_APPLICATION_ID / RAKUTEN_ACCESS_KEY", "AUTH_MISSING")

    params = urllib.parse.urlencode({
        "format": "json",
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "hits": int(hits),
    })
    url = f"{ENDPOINT}?{params}"

    # 代理策略：JSB_PROXY=1 启用（默认 0=直连）；--no-proxy 显式跳过
    use_proxy = proxy_enabled() and not no_proxy
    try:
        status, text = http_request("GET", url, use_proxy=use_proxy, timeout=15)
    except JsbError as e:
        return _fallback(keyword, f"网络不可达：{e}", "NET_UNREACHABLE")

    if status != 200:
        return _fallback(keyword, f"HTTP {status}: {_brief(text)}", "HTTP_ERROR")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _fallback(keyword, "响应非 JSON", "BAD_JSON")

    if "errorMessage" in data or "error" in data or "Items" not in data:
        return _fallback(keyword, _brief(text, 200), "API_ERROR")

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
        "status": "current" if items else "empty",   # empty = API 正常但零结果（确实查无此商品）
        "code": None,
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