# Human-in-the-loop 协议

## 1. 介入原则

Human Request 是持久化的一等实体，不是临时 UI 弹窗。Agent 在等待期间 MUST 停止执行相关任务，不得通过另一个工具路径绕过等待。

## 2. 请求结构

```json
{
  "request_id": "uuid",
  "task_id": "uuid",
  "action_id": "uuid",
  "reason_code": "PRICE_CHANGED",
  "risk_level": "R4",
  "summary": "订单总价发生变化",
  "facts": {
    "product": "...",
    "old_price": "299.00",
    "current_price": "349.00",
    "address_label": "默认家庭地址"
  },
  "options": ["approve", "reject", "edit_constraints"],
  "expires_at": "UTC datetime",
  "default_on_timeout": "pause",
  "status": "PENDING"
}
```

## 3. 必须介入的情况

- 最终提交订单或任何 R4 动作；
- 价格、商品、规格、地址或平台发生变化；
- 登录、验证码或身份验证需要用户操作；
- 任务计划需要超出原始约束；
- 发现多个候选且无法依据策略唯一选择；
- 执行结果未知；
- Agent 需要发送敏感信息或对外通信。

## 4. 用户响应

允许的响应：

```text
APPROVE
REJECT
EDIT_CONSTRAINTS
PAUSE
CANCEL
TAKE_OVER
```

响应 MUST 引用 `request_id`、用户身份和当前任务 `revision`。重复响应必须幂等；过期响应必须拒绝。

## 5. 展示要求

确认界面 MUST 展示：

1. 即将发生的动作；
2. 目标平台和对象；
3. 最终金额、币种和费用；
4. 目标地址的非敏感摘要；
5. 与原策略的差异；
6. 可能的不可逆影响；
7. 授权有效期；
8. 取消和接管选项。

不得只显示“是否继续”。

## 6. 通知与可靠性

- WebSocket 只用于实时展示，最终状态以持久化记录为准。
- 通知发送失败不得改变任务状态；应重试并保留未读请求。
- 用户未响应时默认 `pause`，不得默认批准。
- 连接断开后重新连接，客户端 MUST 拉取未完成的 Human Request。

