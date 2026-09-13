# Action Protocol

## 1. 作用

Action 是 LLM 与确定性执行器之间唯一的业务协议。LLM 不得输出任意 Shell、任意 URL 导航或未注册的动作。

## 2. 通用结构

```json
{
  "action_id": "uuid",
  "task_id": "uuid",
  "action_type": "ecommerce.inspect_product",
  "arguments": {},
  "risk_level": "R1",
  "side_effect": false,
  "reversible": true,
  "required_scopes": ["commerce.read"],
  "preconditions": [],
  "expected_effect": "读取商品价格、库存和规格",
  "verification": {
    "method": "schema",
    "required_fields": ["product_id", "price", "stock"]
  },
  "rollback": null,
  "idempotency_key": "task/action/attempt",
  "timeout_seconds": 15,
  "retry_policy": {
    "max_attempts": 0,
    "backoff_ms": 250
  }
}
```

## 3. 字段约束

- `action_id` 和 `task_id` MUST 是 UUID。
- `action_type` MUST 来自版本化注册表，例如 `ecommerce.v1.inspect_product`。
- `arguments` MUST 通过 Pydantic/schema 校验，禁止额外字段。
- `risk_level` 只能是 `R0`..`R4`。
- `side_effect=true` 时 `idempotency_key` 必填。
- `retry_policy.max_attempts` 范围为 0..3；有副作用或非幂等动作默认必须为 0。
- 单动作超时范围为 1..300 秒；`R4` 动作上限为 30 秒。
- `verification` MUST 描述如何判断动作真实成功。

## 4. 动作生命周期

```text
PROPOSED → POLICY_CHECKED → APPROVED → STARTED → SUCCEEDED
                                      ↘ FAILED
                                      ↘ TIMED_OUT
                                      ↘ CANCELLED
```

每次生命周期变化都生成事件。动作执行器 MUST 在开始前再次检查策略和前置条件。

## 5. 第一阶段动作注册表

| 动作 | 风险 | 副作用 | 默认审批 |
|---|---:|---:|---|
| `ecommerce.search` | R0 | 否 | 无 |
| `ecommerce.inspect_product` | R0 | 否 | 无 |
| `ecommerce.compare_prices` | R0 | 否 | 无 |
| `ecommerce.monitor_stock` | R1 | 否 | 无 |
| `ecommerce.select_variant` | R1 | 否 | 无 |
| `ecommerce.add_to_cart` | R1 | 是 | 条件 |
| `ecommerce.fill_order_preview` | R2 | 是 | 条件 |
| `ecommerce.submit_order` | R4 | 是 | 始终 |

第一阶段禁止注册 `pay`、`delete`、`captcha_bypass` 等动作。

## 6. 执行器边界

执行器 MUST：

- 只接受已注册的 `action_type`；
- 使用服务端注入的用户和租户上下文；
- 不信任模型提供的 `user_id`、权限、地址 ID 或审批令牌；
- 限制输出大小和执行时间；
- 返回结构化结果和验证证据；
- 对超时、部分成功和未知结果显式返回，不得伪造成功。

