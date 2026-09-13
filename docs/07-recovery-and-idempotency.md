# 恢复、幂等与补偿

## 1. 基本原则

网络超时不等于动作失败。对有副作用的动作，执行器必须区分：

```text
SUCCEEDED
FAILED_BEFORE_EFFECT
FAILED_AFTER_EFFECT
UNKNOWN
```

`UNKNOWN` 状态不得自动重试或再次提交，必须先查询外部状态或请求用户介入。

## 2. 幂等键

格式：

```text
{task_id}:{action_type}:{semantic_input_hash}
```

服务端保存幂等记录：

```text
idempotency_key
action_id
request_hash
external_reference
result_hash
status
created_at
expires_at
```

同一 key 的请求参数哈希不一致时，必须报冲突，而不是复用旧结果。

## 3. 检查点

检查点至少记录：

```text
checkpoint_id
task_id
task_revision
completed_action_ids
external_references
policy_version
state_snapshot_hash
created_at
```

第一阶段检查点：

```text
plan-approved
candidate-selected
cart-ready
order-preview-ready
human-approved
order-submitted
```

## 4. 恢复流程

```text
获取任务租约
→ 读取最后检查点
→ 查询未完成动作
→ 查询外部对象状态
→ 校验策略和授权
→ 选择继续、暂停或重新规划
```

恢复器不得从 LLM 的自然语言记忆推断已完成动作。

## 5. 重试规则

- 只读 R0/R1 动作可指数退避重试，最多 3 次；
- 有副作用动作默认不自动重试；
- 仅当执行器明确支持幂等且外部状态可验证时，才允许一次受控重试；
- 验证失败与执行失败分开计数；
- 连续 3 次同类失败后转 `FAILED` 或 `WAITING_FOR_HUMAN`。

## 6. 取消与补偿

取消任务必须阻止新动作并撤销未使用授权。已经产生的外部副作用不能假设可回滚；若存在取消 API，应创建明确的补偿动作并再次经过策略检查。

