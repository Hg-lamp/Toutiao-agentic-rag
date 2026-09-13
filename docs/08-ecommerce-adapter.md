# 电商监控与比价适配器

## 1. 适配器职责

电商适配器负责把通用任务翻译成平台无关的业务动作，不得实现任务状态机、审批逻辑或权限判断。

```text
parse_goal
search
inspect_product
compare
monitor
prepare_order
submit_after_approval
verify_order
```

## 2. 领域数据

```text
ProductCandidate:
  platform
  product_id
  title
  url
  price: Decimal
  currency
  stock_status
  variants
  seller
  evidence
  observed_at

OrderPreview:
  product_id
  variant
  item_price
  shipping_fee
  discount
  total_amount
  currency
  address_ref
  observed_at
  state_hash
```

金额必须以 Decimal 表示；所有价格必须带币种和观察时间。

## 3. 任务参数

```json
{
  "platforms": ["approved.example"],
  "product_query": "无线耳机",
  "required_variants": {"color": ["黑色"]},
  "max_price": "399.00",
  "currency": "CNY",
  "scheduled_at": "UTC datetime",
  "expires_at": "UTC datetime",
  "address_ref": "default_home",
  "allow_substitution": false,
  "max_candidates": 10
}
```

约束：

- `max_candidates` 范围 1..50；
- 查询长度 1..500；
- 平台必须在服务端允许列表；
- 未提供币种时不得猜测，必须询问用户；
- `allow_substitution=false` 时库存不足直接暂停或结束；
- 默认不自动支付。

## 4. 比价和选择

适配器必须返回候选的原始证据和选择理由。LLM 可以排序，但最终筛选必须由确定性策略再次检查：

```text
域名允许
商品匹配
规格匹配
总价 <= max_price
库存有效
币种一致
```

无法唯一选择时进入 `WAITING_FOR_HUMAN`，不得使用“看起来最像”的商品替代。

## 5. 订单准备

准备阶段可以执行：

- 选择规格；
- 加入购物车；
- 读取默认地址的脱敏摘要；
- 填写订单预览；
- 计算总价。

提交前必须重新读取商品、库存、规格、地址和总价，并计算 `state_hash`。任一字段变化都使原确认失效。

## 6. 平台异常

| 异常 | 处理 |
|---|---|
| 登录失效 | `REQUIRES_AUTH`，通知用户 |
| 验证码 | `REQUIRES_CAPTCHA`，不绕过 |
| 商品下架 | `REQUIRES_REPLAN` |
| 库存不足 | 按替代策略暂停或结束 |
| 价格上涨 | 重新请求确认 |
| 页面结构变化 | 暂停并记录证据 |
| 请求被平台拒绝 | `BLOCKED`，不得切换规避路径 |

