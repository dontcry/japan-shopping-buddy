# PayPal 沙箱 API 文档

> 调用实现见 `scripts/paypal_billing.py`。凭证不入代码，读环境变量 `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`。

## 端点

| 动作 | 方法 | 端点 |
|---|---|---|
| OAuth 换 token | POST | `https://api-m.sandbox.paypal.com/v1/oauth2/token` |
| 创建订单 | POST | `https://api-m.sandbox.paypal.com/v2/checkout/orders` |

## 认证

OAuth：`Basic`（base64(`client_id:secret`)）+ 表单体 `grant_type=client_credentials`，返回 `access_token`（scope 含 payments / invoicing 等）。

后续调 Orders 用 `Authorization: Bearer <access_token>`。

## 创建订单（intent=CAPTURE）

```json
{
  "intent": "CAPTURE",
  "purchase_units": [{
    "reference_id": "japan-shopping-buddy",
    "description": "<商品名>",
    "amount": {"currency_code": "JPY", "value": "16500.00"}
  }]
}
```

返回 `order_id`、`status`（CREATED/PAYER_ACTION_REQUIRED）、`links` 中的 `approve` 链接。

## 支付闭环（双轨定位）

- **实际购买始终发生在日本电商 / 代拍商**（乐天 RWS 无下单 API、中古/代拍无公开下单 API）；Skill 不自动替用户下单，成交由用户/代拍商在对应页面完成。
- **华为赛（中立工具）**：PayPal 仅作「支付动作演示 / 可选增强」，弱化收款角色。
- **PayPal 赛（Agentic Commerce）**：PayPal 作「收款闭环演示」——沙箱 merchant 走完整 Orders「创建→approve→capture」，证明 Agent 能发起并完成一笔跨境支付。

## 安全边界

- 永不自动 approve / capture；下单、扣款必须用户二次确认。
- Token 401 时自动重走 OAuth 换 token。
