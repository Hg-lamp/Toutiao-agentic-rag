# 权限、策略与风险模型

## 1. 风险等级

| 等级 | 含义 | 示例 | 规则 |
|---|---|---|---|
| R0 | 只读、无副作用 | 搜索、读取公开页面 | 可自动执行 |
| R1 | 可逆、低影响 | 加购、筛选规格 | 按用户策略自动执行 |
| R2 | 可能暴露个人信息或改变用户状态 | 填写地址、创建草稿 | 默认条件审批 |
| R3 | 对外产生明显影响 | 发送消息、提交非支付表单 | 必须明确授权 |
| R4 | 不可逆或财务/安全高风险 | 最终下单、支付、删除 | 每次操作必须实时确认 |

风险等级只能由服务端注册表定义，LLM 不能降低等级。

## 2. 权限范围

权限使用最小化 scope：

```text
commerce.read
commerce.cart.write
commerce.order.prepare
commerce.order.submit
profile.address.read
notification.send
```

第一阶段默认：

- `commerce.read` 可由任务计划授予；
- `commerce.cart.write` 需用户在计划确认时授予；
- `commerce.order.prepare` 需任务级授权；
- `commerce.order.submit` 只接受一次性、短时授权；
- `profile.address.read` 只能读取用户选择的默认地址引用；
- 不提供支付 scope。

## 3. 策略结构

```json
{
  "policy_version": 1,
  "allowed_domains": ["approved.example"],
  "max_price": "399.00",
  "currency": "CNY",
  "allowed_variants": {"color": ["black", "white"]},
  "default_address_id": "address-ref",
  "allow_substitution": false,
  "require_confirmation": ["commerce.submit_order"],
  "deny_actions": ["payment", "captcha_bypass"],
  "expires_at": "UTC datetime"
}
```

金额必须使用 Decimal 和明确币种，禁止使用二进制浮点。最终金额超过 `max_price`、币种不一致或优惠导致金额无法确认时，必须进入 `WAITING_FOR_HUMAN`。

## 4. 授权令牌

授权绑定以下范围：

```text
user_id
tenant_id
task_id
action_type
target_domain
argument_hash
max_amount
issued_at
expires_at
single_use
```

`R4` 授权 MUST `single_use=true`，默认有效期 10 分钟。目标商品、规格、金额、地址或平台发生变化时，原授权立即失效。

## 5. 永久拒绝条件

以下情况不得通过用户确认绕过：

- 需要绕过验证码或访问控制；
- 需要提取或暴露支付凭据；
- 目标域名不在允许列表；
- 请求与平台规则或法律要求冲突；
- 参数无法确定且可能造成重大损失；
- 执行器返回未知结果而无法确认是否成功。

