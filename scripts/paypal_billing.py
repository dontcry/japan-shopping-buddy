# -*- coding: utf-8 -*-
"""PayPal 沙箱：OAuth 换 token + 创建日元订单（intent=CAPTURE）。

⚠️ 仅创建订单并返回 approve 链接，永不自动 approve / capture（支付须用户二次确认）。

用法：
  PAYPAL_CLIENT_ID=.. PAYPAL_CLIENT_SECRET=.. python3 paypal_billing.py get-token
  PAYPAL_CLIENT_ID=.. PAYPAL_CLIENT_SECRET=.. python3 paypal_billing.py create-order --amount-jpy 16500 --item-name "LYCEE POD020-LYB"
"""
import argparse
import json

from _common import load_secrets, http_request, basic_auth, JsbError

TOKEN_URL = "https://api-m.sandbox.paypal.com/v1/oauth2/token"
ORDERS_URL = "https://api-m.sandbox.paypal.com/v2/checkout/orders"


def get_token(secrets=None):
    secrets = secrets or load_secrets()
    cid = secrets.get("PAYPAL_CLIENT_ID")
    sec = secrets.get("PAYPAL_CLIENT_SECRET")
    if not cid or not sec:
        raise JsbError("缺少 PayPal 凭证：请设置 PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET")

    status, text = http_request(
        "POST", TOKEN_URL,
        headers={"Authorization": basic_auth(cid, sec),
                 "Content-Type": "application/x-www-form-urlencoded"},
        body="grant_type=client_credentials",
        use_proxy=False, timeout=25,
    )
    if status != 200:
        raise JsbError(f"PayPal OAuth 失败 HTTP {status}: {text[:200]}")
    data = json.loads(text)
    return {
        "access_token": data.get("access_token"),
        "token_type": data.get("token_type"),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope"),
    }


def create_order(amount_jpy, item_name, secrets=None):
    token = get_token(secrets)["access_token"]
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": "japan-shopping-buddy",
            "description": item_name,
            "amount": {"currency_code": "JPY", "value": f"{float(amount_jpy):.2f}"},
        }],
    }
    status, text = http_request(
        "POST", ORDERS_URL,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Prefer": "return=representation"},
        body=json.dumps(body),
        use_proxy=False, timeout=25,
    )
    if status not in (200, 201):
        raise JsbError(f"PayPal Orders 失败 HTTP {status}: {text[:200]}")
    data = json.loads(text)
    approve = next((l["href"] for l in data.get("links", []) if l.get("rel") == "approve"), None)
    return {
        "order_id": data.get("id"),
        "status": data.get("status"),
        "amount": {"currency_code": "JPY", "value": f"{float(amount_jpy):.2f}"},
        "item_name": item_name,
        "approve_link": approve,
        "note": "订单已创建（未付款）。请用户点击 approve_link 完成付款；切勿自动 approve/capture。",
    }


def main():
    ap = argparse.ArgumentParser(description="PayPal 沙箱订单")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("get-token")
    co = sub.add_parser("create-order")
    co.add_argument("--amount-jpy", type=float, required=True)
    co.add_argument("--item-name", default="日本商品")
    args = ap.parse_args()

    try:
        if args.cmd == "get-token":
            result = get_token()
        else:
            result = create_order(args.amount_jpy, args.item_name)
    except JsbError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
