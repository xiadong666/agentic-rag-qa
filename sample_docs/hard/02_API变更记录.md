# API 变更记录（Changelog）

本文件记录开放平台对外 API 的**全部**变更。**同一接口出现多条变更时，以最新版本为准**。

---

## v1.0.0（2024-05-06）

- 首次发布三个接口：`GET /v1/customers`、`POST /v1/orders`、`GET /v1/orders/{id}`。
- 鉴权使用 `X-Api-Key`（长期有效）。
- 分页参数：`page`（从 **0** 开始）、`size`（默认 20，最大 100）。

## v1.2.0（2024-08-19）

- `GET /v1/orders/{id}` 增加字段 `channel`，取值 `web` / `app` / `pos`。
- 限流从「固定 100 QPS」改为「按套餐分级」，免费版 20 QPS。
- **弃用** `X-Api-Key`，改用 `Authorization: Bearer <token>`（老方式保留到 2025-06-30）。

## v1.5.0（2024-12-02）

- 新增批量查询：`POST /v1/orders/batch`，单次最多 **50** 个订单号。
- 分页参数改名：`page` → `offset`（仍从 **0** 开始），`size` 上限提高到 **200**。
  老参数名保留一个版本，但**返回体中会带 `deprecated_params` 提示**。
- 错误响应结构统一为 `{"code": "...", "message": "...", "request_id": "..."}`。

## v2.0.0（2025-04-15）**（破坏性变更）**

- **路径前缀变更**：`/v1/**` → `/v2/**`。v1 进入维护期，**2025-12-31 下线**。
- 鉴权升级：`Authorization: Bearer <token>` → 需要在网关申请并携带 `X-Nx-Agt`。
- 分页改为游标：`offset/size` → `cursor` + `limit`（`limit` 默认 **50**，最大 **500**）。
- 订单状态枚举变更（见下表），新增 `refunding` 与 `cancelled`。

| 旧值（v1.x） | 新值（v2.x） | 说明 |
| --- | --- | --- |
| `paying` | `pending_payment` | 仅改名 |
| `paid` | `paid` | 不变 |
| `closed` | `cancelled` | 仅改名 |
| `aftersale` | `refunding` | 语义收窄（仅退款中） |

## v2.1.0（2025-09-01）

- 新增 `GET /v2/orders/{id}/timeline`：返回订单事件时间线（最多 **200** 条）。
- 批量接口上限从 50 提高到 **100**。
- **注意**：`refunding` 之后新增 `refunded` 终态；统计口径里
  「已退款」应统计 `refunded`，**不是** `refunding`。

## v2.2.0（2026-01-20）

- 新增幂等键：`Idempotency-Key` 头，重复提交返回**首次结果**，幂等窗口 **24 小时**。
- 分页 `limit` 上限从 500 提高到 **1000**；**默认值仍为 50**。
- 错误码表新增 `RATE_LIMITED`（HTTP 429）与 `UPSTREAM_TIMEOUT`（HTTP 504）。

## v2.3.0（2026-04-08）

- `GET /v2/orders` 的默认排序从 `created_at desc` 改为 **`updated_at desc`**。
  需要旧行为的显式传 `sort=created_at:desc`。
- 新增字段 `tenant_id`（多租户改造）。
- **已知问题**：`cursor` 分页在 `sort=created_at:desc` 下可能出现**跨页重复**，
  规避方式是显式加上 `id` 作为二级排序（`sort=created_at:desc,id:asc`）。
