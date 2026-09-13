# Personal Mission Agent 双 Agent 工程安排书

## 1. 文档目的

本文用于把 Mission MVP 拆分为两个可以并行开发、最后通过固定协议联调的大任务。后续两个 Agent 必须以本文和 `docs/01` 至 `docs/10` 为共同基线，不得各自重新定义状态、风险等级、Action 字段或 Human Request 语义。

## 2. 总体目标

完成以下最小闭环：

```text
自然语言任务
→ 结构化电商任务
→ 用户确认计划
→ 模拟调度
→ 搜索 / 比价 / 订单准备
→ 风险闸门
→ Human Request
→ 用户批准或拒绝
→ 模拟提交
→ 结果验证、审计和恢复
```

本阶段只实现模拟电商，不接真实平台、不处理支付、不绕过验证码或风控。

## 3. 两个大任务

### Task A：Mission Core —— 通用任务内核与安全控制面

负责“任务能否安全地被创建、执行、暂停、恢复和审计”。

#### A 的职责

- Task、Action、Policy、Risk、HumanRequest、Checkpoint、Event 数据模型；
- 状态机和合法迁移；
- revision 乐观锁；
- 任务租约和并发互斥；
- Action 注册表和结构化参数校验；
- 风险等级与 scope 校验；
- Human-in-the-loop 请求、响应、过期和幂等；
- 调度、暂停、恢复、取消和过期；
- checkpoint、幂等记录和未知结果处理；
- 事件 outbox 和审计查询；
- 面向适配器的稳定 Python 服务接口；
- Core 单元测试和生命周期集成测试。

#### A 不负责

- 商品搜索逻辑；
- 平台页面解析；
- 商品排序和比价策略；
- 浏览器自动化；
- 真实电商平台接入；
- 前端视觉交互；
- 修改现有 RAG 检索流程。

#### A 建议目录

```text
backend/mission/
  domain/
    task.py
    action.py
    policy.py
    risk.py
    human_request.py
    checkpoint.py
    events.py
  application/
    state_machine.py
    orchestrator.py
    action_dispatcher.py
    risk_gate.py
    approval_service.py
    scheduler.py
    recovery_service.py
    verification_service.py
  infrastructure/
    repositories/
    event_store/
    locks/
```

允许新增：

```text
backend/schemas/mission.py
backend/routers/mission.py
test/test_mission_core.py
test/test_mission_recovery.py
```

#### A 的完成标准

1. 能创建并持久化任务；
2. 能拒绝非法状态迁移；
3. 未授权 R3/R4 动作必然被拒绝；
4. `R4` 动作必然生成 Human Request；
5. 用户拒绝、取消、超时后任务不会继续执行；
6. 重复审批响应和重复动作不会产生重复副作用；
7. 服务重启后能从 checkpoint 恢复；
8. `UNKNOWN` 结果不会自动重试；
9. 所有状态变化和动作都有审计事件；
10. 提供 Task B 所需的接口测试和模拟实现。

---

### Task B：Mission Adapter —— 电商任务、模拟执行器与用户交互

负责“一个具体的电商生活任务如何被解析、规划、搜索、比价和准备订单”。

#### B 的职责

- 自然语言到 `ecommerce.purchase` 任务 payload 的解析；
- 电商候选商品、价格、库存和规格模型；
- 模拟电商平台；
- 搜索、详情、比价、库存监控动作；
- 选规格、加购、订单预览和模拟提交动作；
- 电商适配器对 Core Action Protocol 的实现；
- 价格、库存、规格变化的检测；
- 订单提交前生成可读摘要；
- 将需要人工处理的情况转换为 Core 的 Human Request；
- Mission API 的任务创建、查询和用户响应适配；
- 前端或 API 返回所需的任务状态、审批内容和执行结果；
- 电商场景测试和端到端测试。

#### B 不负责

- 自己实现状态机；
- 自己判断授权是否有效；
- 自己签发 approval token；
- 自己决定 R4 是否可绕过人工确认；
- 自己写任务锁、重试和恢复机制；
- 直接访问支付凭据；
- 直接执行任意 Shell 或宿主机命令；
- 改写 Core 的状态和事件协议。

#### B 建议目录

```text
backend/mission/
  adapters/
    ecommerce/
      models.py
      parser.py
      planner.py
      actions.py
      simulator.py
      verifier.py

backend/routers/mission.py
test/test_ecommerce_adapter.py
test/test_mission_e2e.py
```

如果 `backend/routers/mission.py` 与 A 产生冲突，B 必须先使用 A 提供的 service interface，不得把业务逻辑写进路由层。

#### B 的完成标准

1. 自然语言任务能解析成符合 schema 的电商 payload；
2. 模拟平台能复现搜索、库存、价格变化和订单提交；
3. 候选商品筛选始终经过预算、币种、域名和规格检查；
4. 订单预览能展示商品、规格、费用、总价和地址脱敏摘要；
5. 价格或规格变化会让旧审批失效；
6. 验证码、登录失效和平台阻断会暂停任务；
7. 模拟提交只能通过 Core 的有效 R4 授权；
8. 模拟提交超时会产生 `UNKNOWN`，不会重复提交；
9. 与 Core 联调测试通过；
10. 不依赖真实平台和真实支付。

## 4. 两边必须共同遵守的接口

### 4.1 Task Service 接口

Task B 只能通过以下抽象使用 Task A：

```python
class TaskService(Protocol):
    async def create_task(
        self,
        *,
        user_id: int,
        tenant_id: str,
        kind: str,
        goal: str,
        payload: dict[str, object],
        policy_snapshot: dict[str, object],
        scheduled_at: datetime | None,
        expires_at: datetime | None,
    ) -> TaskView: ...

    async def get_task(
        self,
        *,
        user_id: int,
        task_id: UUID,
    ) -> TaskView: ...

    async def cancel_task(
        self,
        *,
        user_id: int,
        task_id: UUID,
        expected_revision: int,
    ) -> TaskView: ...
```

具体类名可以调整，但调用语义和权限边界不能改变。

### 4.2 Action Dispatcher 接口

适配器注册 Action Handler，不直接改变任务状态：

```python
class ActionHandler(Protocol):
    action_type: str

    async def execute(
        self,
        action: Action,
        context: ExecutionContext,
    ) -> ActionResult: ...
```

`ActionResult` 必须明确区分：

```text
SUCCEEDED
FAILED_BEFORE_EFFECT
FAILED_AFTER_EFFECT
UNKNOWN
REQUIRES_HUMAN
```

### 4.3 Human Request 接口

B 只能请求人工介入，不能直接批准：

```python
class ApprovalService(Protocol):
    async def request(
        self,
        *,
        task_id: UUID,
        action_id: UUID,
        reason_code: str,
        facts: dict[str, object],
        options: list[str],
        expires_at: datetime,
    ) -> HumanRequest: ...

    async def respond(
        self,
        *,
        user_id: int,
        request_id: UUID,
        decision: str,
        expected_task_revision: int,
        edits: dict[str, object] | None = None,
    ) -> HumanRequest: ...
```

### 4.4 Event 接口

B 只发布领域事件，不自行写审计表：

```python
await event_bus.publish(
    event_type="ProductCandidateSelected",
    task_id=task_id,
    action_id=action_id,
    payload=payload,
)
```

事件必须由 A 负责信封、顺序、脱敏和持久化。

## 5. 共享固定参数

两边不得各自定义默认值。统一使用以下基线：

| 参数 | 固定值 |
|---|---:|
| 风险等级 | `R0`..`R4` |
| Human Request 默认有效期 | 600 秒 |
| 任务租约 TTL | 30 秒 |
| 租约续期周期 | 10 秒 |
| 单任务默认最大运行时长 | 7200 秒 |
| 最大候选商品数 | 10，允许范围 1..50 |
| 最大自动重试次数 | 3，仅限无副作用幂等动作 |
| R4 自动重试 | 0 |
| 用户未响应默认行为 | `pause` |
| 金额类型 | `Decimal` |
| 时间存储 | UTC |
| 默认支付能力 | 禁用 |
| 默认替代商品 | 禁用 |

## 6. 数据边界

### A 负责的数据

- task；
- task revision；
- task state；
- action；
- authorization；
- human request；
- checkpoint；
- event/outbox；
- idempotency record；
- lease。

### B 负责的数据

- 模拟商品；
- 模拟库存；
- 模拟价格；
- 商品规格；
- 订单预览；
- 模拟订单外部引用；
- 适配器执行证据。

B 的业务数据必须通过 `task_id` 关联任务；不得复制一份 Task 状态作为自己的真相源。

## 7. 依赖与交付顺序

两个任务可以并行，但必须遵循以下依赖：

```text
共同协议确认
        ↓
       A ───────────────┐
        │               │
        └─ 接口测试契约 ──┤
                        ↓
       B ───────→ 集成测试
```

### 开工前

- A 和 B 先阅读 `docs/01` 至 `docs/10`；
- 双方确认 schema、状态值、风险等级和错误码；
- A 先提交接口协议和 fake service；
- B 使用 fake service 并行开发，不等待数据库实现。

### 第一次交接

A 必须交付：

- 可导入的 domain schema；
- 状态机；
- fake TaskService；
- fake ApprovalService；
- ActionDispatcher 接口；
- 事件发布接口；
- A 侧接口测试。

B 必须交付：

- 电商 payload schema；
- 模拟平台；
- ActionHandler 实现；
- 适配器单元测试；
- 不依赖真实平台的执行示例。

### 联调阶段

1. 将 B 的 handler 注册到 A 的 dispatcher；
2. 用 A 的 fake service 跑 B 的端到端测试；
3. 再替换为真实 repository 和 event store；
4. 执行失败恢复、价格变化、重复提交和用户拒绝场景；
5. 修复问题时优先修改协议拥有方，另一侧不得私自兼容冲突语义。

## 8. Git 和文件冲突规则

- A 和 B 不得同时修改同一个核心文件；
- A 拥有 `backend/mission/domain`、`backend/mission/application` 和核心 schema；
- B 拥有 `backend/mission/adapters/ecommerce` 和电商测试；
- API 路由由 A 提供核心服务后，B 只补充电商请求/响应适配；
- 需要跨边界修改时，先新增接口或事件，不直接修改对方实现；
- 任何协议变更必须同步更新 `docs/03`、`docs/04`、`docs/05` 和对应测试；
- 禁止回退或覆盖另一 Agent 的未提交改动。

## 9. 联调验收场景

至少通过以下场景：

1. 创建一个预算内商品监控任务；
2. 任务按计划时间进入运行；
3. 搜索并返回候选商品；
4. 候选排序和价格筛选符合策略；
5. 订单预览生成 Human Request；
6. 用户拒绝后任务终止且不提交；
7. 用户批准后只提交一次；
8. 价格变化使旧审批失效；
9. 库存消失时不购买替代品；
10. 验证码或登录失效进入人工状态；
11. 提交超时进入 `UNKNOWN`，查询确认后再决定；
12. 服务重启后从 checkpoint 恢复且不重复提交；
13. 任务取消后不再执行新的副作用动作；
14. 所有动作、审批、状态迁移均可从审计事件还原。

## 10. “完成”的定义

只有同时满足以下条件，两个大任务才算完成：

- A 的核心测试全部通过；
- B 的适配器和模拟平台测试全部通过；
- 联调验收场景全部通过；
- 没有绕过 Core 的直接副作用路径；
- 没有未授权 R4 路径；
- 没有未知结果自动重试；
- 文档字段、代码 schema 和测试断言一致；
- README 和开发计划已更新为实际状态。

## 11. 后续真实平台接入规则

真实平台只能作为新的 adapter 加入，不能改变 Core：

```text
真实平台 adapter
→ 实现 ActionHandler
→ 声明允许域名和 scope
→ 复用风险闸门、Human Request、幂等和审计
```

在模拟电商联调没有通过前，不得开始真实下单、真实支付或真实平台风控处理。
