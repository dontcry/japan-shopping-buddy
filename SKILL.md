---
name: japan-shopping-buddy
description: >-
  日淘搭子：用户丢来日本商品链接/截图（乐天、Mercari、雅虎拍卖、骏河屋等），
  自动完成日语翻译与商品/成色识别、跨平台比价（全新 vs 中古行情）、
  试算真实到手价（商品+日国内运费+转运+汇率+关税），并生成 PayPal 支付确认单。
  触发：用户说「帮我看看这个日本货到手多少钱」「日淘比价」「海淘下单」，或丢来日本商品链接/截图时。
  不触发：非日本商品、纯国内购物、与商品/比价/支付无关的提问。
---

# Japan Shopping Buddy（日淘搭子）

## 做什么
一句话识别用户给的商品 → 比价 → 试算到手价 → 生成支付确认单（不自动扣款）。

## 指令（按顺序执行，Pipeline 模式）
1. **识别**：解析链接/截图，译出商品名、成色、价格、瑕疵描述与平台来源。
2. **路由**：按「渠道路由决策树」（见 references/channel_routing.md）判断最优渠道。
3. **比价**：优先调一手 API（乐天 RWS，脚本 scripts/rakuten_search.py）查同款/近似款行情；Yahoo / Amazon 因注册门槛放弃，降级为「可用时启用」或代拍中转 / 页面快照兜底；二手/中古源（Mercari / 雅虎拍卖 / 骏河屋）走代拍中转或降级为预置参考价、链接文字识别（见 references/fallback_cache.md）。
4. **试算**：用到手价公式（references/price_formula.md）+ 转运价目（references/forwarding_rates.md），脚本 scripts/arrival_price.py 汇总，标注估算口径 + 汇率快照时间戳。
5. **确认单**：按 assets/confirmation_template.md 生成含明细+总额的 PayPal 支付确认单，交用户确认（Reviewer 卡点）。
6. **支付**：仅当用户二次确认后，脚本 scripts/paypal_billing.py 调 PayPal 沙箱 Orders 创建订单；永不自动 approve。

## 确定性脚本（Tool Wrapper，凭证不入代码）
凭证统一读环境变量（或 `JSB_SECRETS` 指向的本地 JSON），详见各脚本；禁止把 applicationId/accessKey/client_id/secret 写进代码或输出给用户。

| 脚本 | 职责 | 用法 |
|---|---|---|
| scripts/rakuten_search.py | 乐天 RWS 商品搜索/比价（默认走本机代理 127.0.0.1:7890） | `RAKUTEN_APPLICATION_ID=.. RAKUTEN_ACCESS_KEY=.. python3 rakuten_search.py "フィギュア" --hits 5` |
| scripts/exchange_rate.py | JPY→CNY 汇率（双源 + 缓存 + 兜底） | `python3 exchange_rate.py` |
| scripts/arrival_price.py | 到手价试算（商品+转运+手续费+关税） | `python3 arrival_price.py --price-jpy 16500 --channel ems` |
| scripts/paypal_billing.py | PayPal 沙箱 OAuth + 创建订单 | `PAYPAL_CLIENT_ID=.. PAYPAL_CLIENT_SECRET=.. python3 paypal_billing.py create-order --amount-jpy 16500` |

## Gotchas（避坑指南）
- 商品信息不完整（缺成色/尺寸/平台）→ 先追问补全再试算（Inversion：宁缺毋滥，不瞎猜）。
- 日本站直连会被拦（000/403）→ 走本机代理 127.0.0.1:7890；不可达或评委复测网络抖动 → 离线缓存 + Mock 兜底（展示历史基准行情 + 友好提示），绝不抛异常栈。
- 一手比价 API（乐天）只有搜索/行情，无下单/库存 API → 下单与支付只能走 PayPal 沙箱模拟，或用代拍商完成。
- 中古源（骏河屋/Mercari 等）可能被 Cloudflare 403 → 降级为预置参考价或链接文字识别。
- 成色/瑕疵说明是识别推断，非实际值 → 必须标注「估算/待核实」。
- 平台边界：Temu 日本版（中国低价出海，非日本本土商品）、NETSEA/SuperDelivery（B2B 批发）不纳入比价路由，避免误判为日淘货源。

## 禁止行为
- 永不自动 approve / 自动扣款；下单、支付、领券、改地址一律需用户确认。
- 不把凭证（applicationId/accessKey/client_id/secret）写进代码或输出给用户。
- 不承诺精确到手价（汇率/运费/关税实时变动）。
- 不对非日本商品/非购物意图的问题乱触发。

## 退出条件
- 用户拒绝支付确认单 → 停止下单流程，仅保留试算结果。
- 连续 3 次无法获取行情/页面 → 停止重试，明确告知失败原因并给出替代渠道。
- 输入不是日本商品链接/截图 → 说明本 Skill 边界后退出。

## 输入输出示例

输入 1：`帮我看看 item.rakuten.co.jp/azone-int/pod020lyb 到手多少钱`
输出 1：商品=LYCEE YUKATA（POD020-LYB）¥16,500 → 路由=乐天官店→转运 → 到手价≈¥940~980（商品/转运/关税分项）→ 需要我生成 PayPal 支付确认单吗？

输入 2：`这个（截图：日拍娃娃）值不值得`
输出 2：识别=雅虎拍卖 中古娃娃 → 成色「未使用に近い」→ 行情参考 ¥9,500~13,200 → 到手价（含代拍费 ¥300/件 + EMS）≈ ¥xxx → 建议竞拍上限 ¥xxx（标注估算）。

## 参数与依赖
- 乐天凭证 applicationId/accessKey（环境变量）；Yahoo Shopping v3 已放弃（无日本手机号，可用时启用）；Amazon PA-API 已放弃
- PayPal client_id/secret（环境变量）
- 汇率：open.er-api.com/v6（主）/ exchangerate-api.com/v4（备）/ 内置基准 0.04224
- 转运价目：references/forwarding_rates.md（内置常量，标注「估算」）

## 目录（三层架构）
- scripts/：乐天/PayPal 请求、汇率换算、到手价试算脚本（Tool Wrapper）
- references/：channel_routing.md、price_formula.md、forwarding_rates.md、fallback_cache.md、paypal_api.md
- assets/：确认单模板（Generator）、图标
