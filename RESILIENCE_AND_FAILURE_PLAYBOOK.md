# 治理系统异常、故障与交互韧性预案

版本：2026-08-04

适用范围：

- `decision-system-governance`
- `evidence-data-center`
- `compute-simulation-center`
- `expert-assessment-center`
- 网页 GPTs → 治理仓库 → 三个子中心的单线控制链

本文件是正式运行预案，不把“有测试”误写成“所有异常都已解决”。每一类情况必须标记为：

- `IMPLEMENTED`：代码已实现并有真实或静态证据；
- `REQUIRED`：生产前必须补齐；
- `OPERATIONAL`：依赖 GitHub 或人工操作，系统只能提供降级与恢复路径；
- `OUT_OF_SCOPE`：基于安全边界故意不支持。

## 一、不可破坏的总原则

1. 网页 GPTs 只接触治理仓库，不直接接触三个子仓库。
2. `GPTS_GOVERNANCE_TOKEN` 只允许治理仓库 `Metadata: read`、`Issues: read/write`。
3. `CONTROL_PLANE_TOKEN` 只允许三个子仓库 `Metadata: read`、`Issues: read/write`。
4. 所有代码、分支、PR、Workflow、Secrets、Variables、Administration 权限均保持禁止。
5. 全球仅一个治理执行槽，FIFO，禁止并发执行多个业务任务。
6. 子中心之间禁止直连。
7. 只信任 `github-actions[bot]` 的正式终态，用户正文中的状态不构成证据。
8. 重试必须有限、幂等、可审计，禁止无限 Agent 循环和无限重试。
9. 失败必须显式，不能把 Issue 创建成功、工作流启动成功或接口 HTTP 2xx 当成业务成功。
10. 所有终态必须携带任务 ID、子 Issue、调用数量和 Artifact/诊断证据。

## 二、任务生命周期状态机

标准状态：

```text
QUEUED
→ VALIDATING
→ RUNNING
→ DISPATCHED
→ CHILD_ACCEPTED
→ CHILD_TERMINAL
→ CONTROL_COMPLETED / CONTROL_FAILED
→ CHILD_ISSUE_RECLAIMED
```

异常状态：

```text
CONTROL_REJECTED
CONTROL_DUPLICATE
CONTROL_DISPATCH_ERROR
CONTROL_MONITOR_ERROR
CONTROL_TIMEOUT
CONTROL_RETRY_EXHAUSTED
CONTROL_RECONCILED_LATE_SUCCESS
CONTROL_RECONCILED_LATE_FAILURE
```

任何状态跳转都必须满足：

- 任务 ID 不变；
- route 不变；
- 子仓库固定；
- 子 Issue 与任务 ID 一一对应；
- 可信评论作者为 `github-actions[bot]`；
- 成功终态必须满足对应 Artifact 合同。

## 三、异常矩阵与处理预案

### A. 提交与交互错误

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| 用户重复点击或 GPT 重复提交同一任务 | 重复调用、重复费用 | `IMPLEMENTED` | 对业务内容生成指纹，忽略 `wait_seconds`，原任务开放或成功时拒绝新任务并返回 `CONTROL_DUPLICATE`。 |
| 原任务失败后原样重提 | 当前历史失败可能仍被当作 duplicate | `REQUIRED` | duplicate 只应阻止“开放、运行中、成功、已确认 duplicate”的原任务；`not_planned` 失败任务允许新 Issue 重新执行。 |
| 用户把 `wait_seconds` 改成不同值绕过去重 | 重复执行 | `IMPLEMENTED` | 指纹不包含等待时间。 |
| 用户提交错误 route | 路径穿越或误派发 | `IMPLEMENTED` | route 只能为 `compute`、`intelligence`、`expert`。 |
| 用户直接指定子仓库 | 越权绕过路由 | `IMPLEMENTED` | 顶层未知字段如 `repository` 直接拒绝。 |
| 用户伪造 `task_id` | 任务劫持、复用别人结果 | `IMPLEMENTED` | task_id 只能由治理 Issue 编号生成。 |
| 用户夹带 Secret | Secret 泄露到 Issue | `IMPLEMENTED/PARTIAL` | 已递归拦截常见 secret/token/password/api_key 字段；仍需补充 camelCase、authorization、clientSecret 等变体。 |
| 用户夹带 shell/code/script 字段 | 诱导执行任意代码 | `IMPLEMENTED/PARTIAL` | 子中心严格 Schema 已阻止未知执行字段；治理层仍应增加精确危险字段黑名单。 |
| JSON 过大 | 内存、日志与 API 压力 | `IMPLEMENTED` | 请求正文上限 100,000 字符。 |
| JSON 超深嵌套或节点爆炸 | 递归异常、DoS | `REQUIRED` | 增加最大深度、最大节点数、最大单字符串长度，并使用迭代遍历。 |
| NaN/Infinity | 计算与指纹不一致 | `IMPLEMENTED` | 非有限 JSON 数值直接拒绝。 |
| 非 `[control]` 标题 | 错误触发治理 | `IMPLEMENTED` | 只接受标题精确等于 `[control]` 且作者为仓库所有者。 |
| 用户误关排队 Issue | 任务丢失 | `IMPLEMENTED/OPERATIONAL` | 已关闭 Issue 不会被选择；重新打开后可由 FIFO 定时 worker 接管。 |
| 用户在排队时修改任务 | 执行非预期版本 | `IMPLEMENTED` | 选择时读取最终正文并重新校验，非法修改直接拒绝。 |
| 用户在 RUNNING 后修改正文或伪造终态 | 路由劫持、结果欺骗 | `IMPLEMENTED` | worker 使用已冻结票据快照；最终可信回执覆盖用户修改。 |
| 用户在完成后修改正文 | GPT 可能只看到伪造正文 | `REQUIRED` | GPT Action 必须增加只读 comments 查询，并要求验证最新 `github-actions[bot]` 终态；不能只读 Issue body。 |

### B. FIFO、并发与队列故障

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| 多个任务同时提交 | 并发污染、成本失控 | `IMPLEMENTED` | 治理 workflow 使用全局 concurrency group，`cancel-in-progress=false`，FIFO 按 Issue 编号处理。 |
| 无效任务夹在有效任务之间 | 阻塞尾部任务 | `IMPLEMENTED` | 无效任务快速拒绝、调用 0，随后唤醒下一 worker。 |
| 同一任务的多个 workflow run 同时启动 | 双重派发 | `IMPLEMENTED` | 全局 concurrency + 子 Issue 标题幂等复用。 |
| 下一 worker 唤醒失败 | 队列停顿 | `IMPLEMENTED/PARTIAL` | 15 分钟 schedule 会恢复；还应为 `gh workflow run` 增加有限重试和显式降级回执。 |
| GitHub Actions 短时不可用 | 队列无人处理 | `OPERATIONAL` | 恢复后由 schedule 自动继续；无法绕过 GitHub 平台级中断。 |
| 长任务占用唯一槽 | 后续任务等待 | `BY_DESIGN` | 这是串行安全边界；状态必须显示队列与当前任务，不允许并发绕过。 |
| 开放非控制 Issue | 干扰扫描 | `IMPLEMENTED` | 非 `[control]` Issue 被忽略。 |
| 任务数量超过扫描分页 | 老任务或 duplicate 漏检 | `REQUIRED` | 当前最多扫描 1000 个 Issue；应增加基于时间窗/标签/索引的长期归档策略。 |

### C. 派发、Token 与子仓库故障

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| `CONTROL_PLANE_TOKEN` 缺失、过期或撤销 | 无法创建子任务 | `IMPLEMENTED/PARTIAL` | 返回 `CONTROL_DISPATCH_ERROR`，不宣称业务成功；应增加每日只读健康检查与单一健康状态 Issue。 |
| Token 权限被错误扩大 | 代码或配置越权 | `IMPLEMENTED` | 实测代码、分支、PR、Secrets、Workflow 均返回 403；权限合同 CI 阻止配置扩大。 |
| 子 Issue 已存在 | 重复创建 | `IMPLEMENTED` | 按唯一标题复用已有子 Issue。 |
| 专家命令重复发送 | 重复模型调用 | `IMPLEMENTED` | 正常首次命令去重；受控 retry 必须使用唯一 retry_id。 |
| 子 Issue 创建成功但子工作流事件丢失 | 永久无终态 | `REQUIRED` | 若在规定时间内没有任何可信 bot 活动，只允许一次受控重触发：compute/API 关闭后 reopen；expert 重发一次 `/run-expert-team`。必须记录 recovery_id。 |
| 子工作流已接受但中途被取消 | 开放任务与无终态 | `REQUIRED` | 超时后标记为可恢复失败；禁止盲目并发重跑。新任务可重新提交，旧任务进入迟到终态对账。 |
| 子 Issue 被人工编辑 | 票据被篡改 | `IMPLEMENTED/PARTIAL` | 首次 workflow 使用事件快照；受控重试前应校验或恢复治理保存的规范票据。 |
| 子 Issue 被人工关闭 | workflow 仍可能运行 | `OPERATIONAL` | 关闭 Issue 不等于取消 GitHub Actions；系统必须继续观察可信终态。 |
| 子 Issue 终态后仍开放 | 陈旧锁误拒后续任务 | `IMPLEMENTED` | 三中心已加入可信终态自动回收器，成功关闭为 completed，失败关闭为 not_planned，并有 5 分钟兜底扫描。 |

### D. 轮询、超时与迟到结果

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| 单次 GitHub API 网络错误 | 短时误失败 | `IMPLEMENTED` | 轮询继续，连续错误计数归零后恢复。 |
| 连续 5 次轮询错误 | 监控失效 | `IMPLEMENTED/PARTIAL` | 输出 `CONTROL_MONITOR_ERROR`；仍需定时对账器处理迟到终态。 |
| 到达 `wait_seconds` 无终态 | 任务可能仍在执行 | `IMPLEMENTED/PARTIAL` | 输出 `CONTROL_TIMEOUT`，不宣称成功；仍需迟到终态对账。 |
| 超时后子任务晚到成功 | 治理永久显示失败 | `REQUIRED` | 定时对账 closed governance Issue；若任务 ID、route、子 Issue 和可信终态一致，更新为 `CONTROL_RECONCILED_LATE_SUCCESS`。 |
| 超时后子任务晚到失败 | 状态不一致 | `REQUIRED` | 更新为 `CONTROL_RECONCILED_LATE_FAILURE` 并保留原超时证据。 |
| 子 Issue 评论超过 100 条 | 终态位于第二页而漏读 | `REQUIRED` | 所有 comment 查询统一分页，至少 10 页，并从最后一页倒序寻找终态。 |
| GitHub rate limit | 403/429 被当成普通错误 | `REQUIRED` | 识别 `Retry-After` 与 `X-RateLimit-Reset`，指数退避并写入审计。 |
| 评论存在 bot 终态但任务 ID 不匹配 | 误绑定其他任务 | `REQUIRED` | 终态必须包含预期 task_id；不匹配一律忽略并记录安全告警。 |
| 成功评论缺 Artifact | 假成功或交付不完整 | `REQUIRED` | compute/API 成功必须有 Artifact ID、digest、URL；expert 成功必须有最终 attestation Artifact。 |

### E. 子中心自身故障

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| 情报上游 API 500/429/超时 | 数据请求失败 | `IMPLEMENTED/PARTIAL` | 子中心返回结构化 `API_FAILED` 和 retryable；票据可配置有限 max_attempts。治理不能把仓库连通误写成数据成功。 |
| 上游 API 返回 HTTP 200 但无业务数据 | 假成功 | `IMPLEMENTED` | connector response contract 判断 data_present。 |
| API 返回过大内容 | Artifact/评论爆炸 | `IMPLEMENTED` | 每请求响应字节限制，公开评论分块，完整证据进 Artifact。 |
| 计算依赖安装失败 | 计算不执行 | `IMPLEMENTED` | `COMPUTE_FAILED`，模型调用 0，Artifact/诊断保留。 |
| 计算中心网络未隔离 | 数据外泄 | `IMPLEMENTED` | OS network namespace + network assurance。 |
| 专家票据非法 | 仍触发付费模型 | `IMPLEMENTED` | 独立无效票据拒绝器在模型调用前返回 `EXECUTION_REJECTED`，调用 0。 |
| 专家任务已经运行又重复命令 | 重复费用 | `IMPLEMENTED` | admission 状态与 retry_id 去重，最大受控重试次数有限。 |
| 专家执行结果缺审计或 attestation | 假成功 | `IMPLEMENTED` | 只有完整审计、主 Artifact、独立复算和最终 attestation 通过后才能发布成功。 |

### F. 证据、回执与 GPT 交互

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| Issue 创建成功被误解为任务成功 | 错误报告 | `IMPLEMENTED` | GPT 指令必须区分 created、accepted、dispatched、terminal。 |
| 子中心受理成功被误解为业务成功 | 错误报告 | `IMPLEMENTED` | 只认终态和 Artifact。 |
| 用户正文伪造 `CONTROL_COMPLETED` | GPT 被欺骗 | `IMPLEMENTED/PARTIAL` | 治理会拒绝初始伪造；完成后的人工编辑仍需 comments 只读接口验证。 |
| bot 评论被截断 | 关键证据缺失 | `IMPLEMENTED/PARTIAL` | 完整结果进 Artifact；治理摘要最多保留 12,000 字符。应验证 Artifact 合同。 |
| Artifact 上传失败 | 结果无法验证 | `IMPLEMENTED` | 子中心成功条件要求 Artifact 上传成功；否则返回失败。 |
| 用户询问处理中状态 | GPT 无法说明下一步 | `REQUIRED` | 统一状态词典：QUEUED/RUNNING/DISPATCHED/ACCEPTED/COMPLETED/FAILED/TIMEOUT，并给出明确下一动作。 |
| 用户要求立即取消正在运行的任务 | 误以为关闭 Issue 能停掉模型 | `OUT_OF_SCOPE/OPERATIONAL` | 最小权限 Token 无 Actions write，不能远程取消子 workflow。排队任务可关闭；已运行任务只支持协作式停止设计，不宣称即时取消。 |

### G. 安全与灾难恢复

| 场景 | 风险 | 当前状态 | 预案 |
|---|---|---|---|
| Key 泄露 | Issue 操纵 | `OPERATIONAL` | 立即 revoke、重建最小权限 Key、替换 Secret、审计泄露时间窗内所有 Issue 与 workflow。 |
| 仓库被错误改为私有/转移/重命名 | 路由失效 | `REQUIRED` | 每日仓库身份健康检查：owner、repo、visibility、default branch。 |
| main/production 不一致 | 专家执行非正式代码 | `IMPLEMENTED` | 专家 workflow 强制 main=production=checkout SHA。 |
| 生产 workflow 被修改 | 安全边界漂移 | `IMPLEMENTED` | Actions 固定 SHA、权限合同、完整性 CI；分支保护仍应保持 required checks。 |
| GitHub 平台级长期故障 | 全系统不可用 | `OPERATIONAL` | 系统进入显式 `PLATFORM_UNAVAILABLE`，禁止本地或无证据绕过；恢复后从开放治理 Issue 继续。 |
| 证据 Artifact 过期 | 无法长期复核 | `REQUIRED/OPERATIONAL` | 关键生产结果需要外部长期归档或提高保留策略；测试 Artifact 可短期保留。 |

## 四、恢复优先级

### P0：生产阻断，必须补齐

1. 失败任务允许原样重新提交，不能被历史失败永久 duplicate。
2. comments 全分页读取。
3. 终态绑定预期 task_id。
4. 成功终态验证 Artifact/attestation 合同。
5. 超时与监控错误的迟到终态对账。
6. 子工作流完全没有启动时只允许一次受控重触发。
7. GPT Action 增加 comments 只读查询并据此验证机器人终态。
8. JSON 深度、节点数与秘密字段变体防护。

### P1：高优先级

1. rate limit 感知与退避。
2. 下一 worker 唤醒有限重试。
3. Token/仓库身份每日健康检查。
4. 统一用户状态词典与错误说明。
5. 长期 Issue/Artifact 归档策略。

### P2：运维增强

1. 失败率、平均等待时间、超时率与队列长度统计。
2. 每日零调用健康摘要，仅异常时通知。
3. 混沌测试矩阵定期运行，但禁止触发付费模型。
4. 故障演练记录与恢复时间目标。

## 五、标准恢复动作

### 1. 重复提交

```text
原任务 open/running/completed：新任务关闭 duplicate，不派发。
原任务 failed/not_planned：允许新任务，生成新 task_id 和新子 Issue。
```

### 2. 派发失败

```text
记录 CONTROL_DISPATCH_ERROR
→ 子 Issue 未确认则不得宣称创建成功
→ 15 分钟健康 worker 再检查 Token 与仓库
→ 用户可原样重新提交
```

### 3. 子工作流未启动

```text
派发后无任何 github-actions[bot] 活动
→ 等待保护窗口
→ 仅一次 recovery_id
→ compute/API: close + reopen child Issue
→ expert: 重发一次正式 run 命令
→ 仍无活动则失败，不无限重试
```

### 4. 轮询失败或超时

```text
CONTROL_MONITOR_ERROR / CONTROL_TIMEOUT
→ 治理任务关闭为未确认失败
→ 子任务继续作为权威执行位置
→ 定时对账器检查迟到终态
→ 成功则改写为 RECONCILED_LATE_SUCCESS
→ 失败则改写为 RECONCILED_LATE_FAILURE
```

### 5. 陈旧子 Issue

```text
发现可信终态
→ 自动关闭 child Issue
→ success = completed
→ failed/rejected = not_planned
→ 定时兜底再次扫描
```

### 6. Key 失效

```text
禁止扩大权限临时绕过
→ revoke 旧 Key
→ 重新创建相同最小权限 Key
→ 更新对应 Secret
→ 运行 Issues 正向测试 + 代码/PR/Secrets/Workflow 负向 403 测试
```

## 六、验收门槛

只有同时满足以下条件，才能宣称“复杂使用条件下稳定”：

1. 30+ 类异常测试均有明确终态；
2. 所有非法输入子派发为 0；
3. 所有 duplicate 子派发为 0；
4. FIFO 顺序在突发队列中保持；
5. 运行中和排队期篡改不能改变冻结任务；
6. 三中心终态子 Issue 自动回收；
7. 超时迟到结果可以自动对账；
8. 历史失败允许正常重新提交；
9. 1000 条评论规模下仍能找到终态；
10. 成功状态与 task_id、Artifact、digest、子 Issue 一致；
11. Key 权限负向测试持续为 403；
12. 模型调用与费用测试必须按任务要求明确回执。

## 七、当前结论

截至 2026-08-04：

```text
最小权限与越权防护：通过
三中心正式派发：通过
FIFO 与突发队列：通过
重复成功任务去重：通过
非法输入隔离：通过
运行中篡改防护：通过
排队期篡改防护：通过
三中心终态 Issue 自动回收：通过

完整灾难恢复与交互韧性：尚未全部完成
生产韧性状态：CONDITIONAL_PASS
```

在 P0 八项全部实现并复测前，不得写成“所有复杂意外情况都已全面解决”。
