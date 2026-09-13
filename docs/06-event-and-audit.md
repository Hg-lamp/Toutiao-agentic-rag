# 事件、审计与可观测性

## 1. 事件信封

```json
{
  "event_id": "uuid",
  "event_type": "ActionCompleted",
  "schema_version": 1,
  "task_id": "uuid",
  "action_id": "uuid or null",
  "user_id": 123,
  "tenant_id": "default",
  "trace_id": "uuid",
  "occurred_at": "UTC datetime",
  "sequence": 42,
  "payload": {},
  "redaction": ["address.full_text"]
}
```

事件写入 MUST 在任务状态写入之前或通过同一事务 outbox 完成，不能只写日志。

## 2. 事件类型

```text
TaskCreated
PlanGenerated
PlanApproved
ActionProposed
ActionPolicyDenied
ActionStarted
ActionCompleted
ActionFailed
HumanInputRequired
HumanDecisionRecorded
CheckpointCreated
TaskPaused
TaskResumed
TaskCancelled
TaskExpired
TaskCompleted
TaskFailed
```

## 3. 审计要求

必须能够回答：

- 用户原始目标是什么；
- Agent 生成了什么计划；
- 使用了哪些工具和参数摘要；
- 哪个策略允许了动作；
- 哪个用户在什么时候批准了什么；
- 外部系统返回了什么证据；
- 失败、重试和恢复经过了哪些步骤。

## 4. 敏感数据

- 日志不得写入密码、验证码、完整支付信息、完整地址或会话 Cookie。
- 地址只记录稳定引用和脱敏标签。
- 工具参数使用结构化脱敏器，禁止通过字符串替换猜测敏感字段。
- 审计事件保留原始内容的哈希，必要时保存加密后的最小副本。
- 默认保留 90 天；过期后删除正文，仅保留聚合指标和不可逆哈希。

## 5. 指标

至少记录：

```text
task_created_total
task_completed_total
task_failed_total
task_paused_total
human_request_wait_seconds
action_latency_seconds
action_retry_total
policy_denied_total
unknown_result_total
duplicate_side_effect_prevented_total
```

