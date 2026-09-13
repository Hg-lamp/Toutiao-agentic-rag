# Task 状态机与生命周期

## 1. 状态集合

```text
DRAFT
PLANNED
WAITING_FOR_SCHEDULE
RUNNING
WAITING_FOR_HUMAN
RESUMING
VERIFYING
COMPLETED
PAUSED
CANCELLED
FAILED
EXPIRED
BLOCKED
REQUIRES_AUTH
REQUIRES_CAPTCHA
REQUIRES_REPLAN
```

终态为：`COMPLETED`、`CANCELLED`、`FAILED`、`EXPIRED`、`BLOCKED`。

## 2. 合法迁移

| 当前状态 | 允许迁移 |
|---|---|
| `DRAFT` | `PLANNED`, `CANCELLED` |
| `PLANNED` | `WAITING_FOR_SCHEDULE`, `RUNNING`, `CANCELLED` |
| `WAITING_FOR_SCHEDULE` | `RUNNING`, `EXPIRED`, `CANCELLED`, `PAUSED` |
| `RUNNING` | `WAITING_FOR_HUMAN`, `PAUSED`, `REQUIRES_AUTH`, `REQUIRES_CAPTCHA`, `REQUIRES_REPLAN`, `VERIFYING`, `FAILED`, `CANCELLED` |
| `WAITING_FOR_HUMAN` | `RESUMING`, `PAUSED`, `CANCELLED`, `EXPIRED` |
| `RESUMING` | `RUNNING`, `WAITING_FOR_HUMAN`, `REQUIRES_REPLAN`, `FAILED` |
| `VERIFYING` | `COMPLETED`, `WAITING_FOR_HUMAN`, `REQUIRES_REPLAN`, `FAILED` |
| `PAUSED` | `WAITING_FOR_SCHEDULE`, `RUNNING`, `CANCELLED`, `EXPIRED` |
| `REQUIRES_AUTH` | `RESUMING`, `PAUSED`, `CANCELLED`, `EXPIRED` |
| `REQUIRES_CAPTCHA` | `RESUMING`, `PAUSED`, `CANCELLED`, `EXPIRED` |
| `REQUIRES_REPLAN` | `PLANNED`, `WAITING_FOR_HUMAN`, `CANCELLED`, `FAILED` |

状态机实现 MUST 拒绝表外迁移。LLM 只能产生迁移意图，不能直接写入状态。

## 3. 任务字段

```text
task_id: UUID
user_id: positive integer
tenant_id: 1..64 characters
kind: string, e.g. "ecommerce.purchase"
goal: 1..4000 characters
status: TaskStatus
payload: versioned JSON object
policy_snapshot: immutable JSON object
plan_version: positive integer
current_action_id: UUID or null
created_at / updated_at: UTC datetime
scheduled_at: UTC datetime or null
expires_at: UTC datetime or null
last_checkpoint_id: UUID or null
revision: non-negative integer
```

所有写操作 MUST 使用 `revision` 乐观锁；更新条件不匹配时返回冲突，不得覆盖其他执行器的状态。

## 4. 调度参数

- 任务时钟统一使用 UTC 存储，展示时使用用户时区。
- `scheduled_at` 必须早于 `expires_at`。
- 调度轮询间隔默认 1 秒，允许通过配置调整为 1..60 秒。
- 单个任务默认最大运行时长 2 小时。
- 用户确认默认有效期 10 分钟；过期必须重新请求确认。
- 同一 `task_id` 同时只能有一个活动执行租约。
- 租约默认 TTL 30 秒，续租周期 10 秒；失联后由恢复器接管。

## 5. 暂停和恢复

暂停必须记录原因、当前动作、检查点和恢复条件。恢复时 MUST 重新检查：

1. 任务未进入终态；
2. 用户策略版本未撤销；
3. 授权未过期；
4. 外部对象仍匹配；
5. 当前动作的幂等键未成功执行。

