# 治理系统异常、故障与交互韧性预案

版本：2026-08-05

适用范围：

- `decision-system-governance`
- `evidence-data-center`
- `compute-simulation-center`
- `expert-assessment-center`
- 网页 GPTs → 治理仓库 → 三个子中心的单线控制链

本文件区分四种证据状态：

- `IMPLEMENTED`：生产代码已经实现；
- `DETERMINISTIC_TESTED`：仓库内确定性测试已经通过，不调用付费模型；
- `LIVE_ACCEPTED`：合并后的正式 Issue/Actions 链已经真实验收；
- `OPERATIONAL`：依赖 GitHub 或人工平台操作，不能在现有最小权限边界内完全自动化。

不得把代码存在、Issue 创建成功、工作流启动成功或 HTTP 2xx 写成业务成功。正式成功必须由可信终态、正确 Task ID 和对应 Artifact 共同证明。

## 一、不可破坏的边界

1. 网页 GPTs 只访问治理仓库，不直接访问三个子仓库。
2. `GPTS_GOVERNANCE_TOKEN` 只应拥有治理仓库 `Metadata: read`、`Issues: read/write`。
3. `CONTROL_PLANE_TOKEN` 只应拥有三个子仓库 `Metadata: read`、`Issues: read/write`。
4. GPT 与控制 Token 均不得拥有 Contents、Branches、Pull requests、Actions、Workflows、Secrets、Variables、Administration 等写权限。
5. 治理全局只有一个执行槽，FIFO，`cancel-in-progress=false`。
6. 子中心之间禁止直连。
7. 只信任 `github-actions[bot]` 的正式状态评论；Issue 正文仅是便捷视图。
8. 重试必须有限、幂等、带唯一标记，禁止无限 Agent 循环。
9. 超时不等于取消，关闭 Issue 不等于停止已经运行的 GitHub Actions。
10. 任何恢复不得通过临时扩大 Token 权限实现。

## 二、任务状态机

正常链：

```text
QUEUED
→ VALIDATING
→ CONTROL_RUNNING
→ CONTROL_DISPATCHED
→ CHILD_ACCEPTED
→ CHILD_TERMINAL
→ CONTROL_COMPLETED / CONTROL_FAILED
→ CHILD_ISSUE_RECLAIMED
```

异常链：

```text
CONTROL_REJECTED
CONTROL_DUPLICATE
CONTROL_DISPATCH_ERROR
CONTROL_MONITOR_ERROR
CONTROL_TIMEOUT
CONTROL_RETRY_EXHAUSTED
CONTROL_CHILD_TASK_MISMATCH
CONTROL_CHILD_EVIDENCE_INVALID
CONTROL_RECONCILED_LATE_SUCCESS
CONTROL_RECONCILED_LATE_FAILURE
```

所有状态必须保持：

- 治理 Issue 编号不变；
- `route` 不变；
- Task ID 由治理生成并与子 Issue 一一对应；
- 子仓库只能由 route 决定；
- 终态作者必须为 `github-actions[bot]`；
- 成功必须满足路由对应 Artifact 合同。

## 三、提交、重复与交互异常

| 场景 | 当前处理 | 状态 |
|---|---|---|
| 用户或 GPT 重复点击 | 业务内容生成规范指纹；`wait_seconds` 不参与指纹 | `LIVE_ACCEPTED` |
| 原任务仍开放、运行中或已成功 | 新任务关闭为 `CONTROL_DUPLICATE`，子派发为 0 | `LIVE_ACCEPTED` |
| 原任务失败或 `not_planned` 后原样重提 | 不再由历史失败污染指纹；新 Issue 获得新 Task ID | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 错误 route 或路径穿越 | 只允许 `compute`、`intelligence`、`expert` | `LIVE_ACCEPTED` |
| 用户指定 repository | 顶层未知字段拒绝，不派发 | `LIVE_ACCEPTED` |
| 用户指定 task_id | 拒绝；Task ID 只由治理 Issue 编号生成 | `LIVE_ACCEPTED` |
| Secret 夹带 | 拦截 token、secret、password、apiKey、accessToken、clientSecret、authorization 等规范变体 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| shell/code/script 夹带 | 拦截 shell、command、script、pythonCode、powershell、eval、exec 等执行字段 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 超深或爆炸 JSON | 限制正文、深度、节点数、Key 长度和单字符串长度；使用迭代遍历 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| NaN/Infinity | JSON 解析阶段拒绝 | `LIVE_ACCEPTED/STATIC` |
| 非 `[control]` 标题 | 不进入治理队列 | `LIVE_ACCEPTED` |
| 排队期间编辑正文 | worker 选择时读取最终正文并重新校验 | `LIVE_ACCEPTED` |
| RUNNING 后编辑正文或伪造状态 | 执行使用冻结快照，最终可信回执覆盖编辑 | `LIVE_ACCEPTED` |
| 完成后编辑 Issue 正文 | GPT 必须读取 comments 并验证最新可信机器人回执，不能仅信任正文 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` + `OPERATIONAL` |

`OPERATIONAL` 边界：仓库中的 OpenAPI 更新不会自动进入现有自定义 GPT；必须在 GPT 配置中重新导入或更新 Action schema，新的只读 comments 操作才会可用。

## 四、FIFO、并发与队列异常

| 场景 | 当前处理 | 状态 |
|---|---|---|
| 多任务突发提交 | 全局 concurrency group 串行处理，FIFO 按 Issue 编号 | `LIVE_ACCEPTED` |
| 无效任务夹在有效任务之间 | 无效任务零调用快速拒绝，继续唤醒尾部任务 | `LIVE_ACCEPTED` |
| 多个 worker 同时启动 | 全局执行槽防并发；子 Issue 按唯一标题幂等复用 | `LIVE_ACCEPTED` |
| 下一 worker 主动唤醒失败 | 15 分钟 schedule 兜底恢复 | `IMPLEMENTED/PARTIAL` |
| GitHub Actions 短时中断 | 平台恢复后 schedule 继续扫描开放治理 Issue | `OPERATIONAL` |
| 长任务占用唯一槽 | 后续任务等待，不允许绕过串行边界 | `BY_DESIGN` |
| 开放非控制 Issue | 扫描时忽略 | `LIVE_ACCEPTED` |
| 子任务终态后仍开放 | 三中心可信终态回收器自动关闭，并有 5 分钟兜底扫描 | `LIVE_ACCEPTED` |

仍属 P1：下一 worker 的 `gh workflow run` 应增加有限重试和显式唤醒失败回执。

## 五、派发、Token 与子工作流异常

| 场景 | 当前处理 | 状态 |
|---|---|---|
| `CONTROL_PLANE_TOKEN` 缺失、过期或撤销 | 返回 `CONTROL_DISPATCH_ERROR`，不得宣称子 Issue 已创建 | `IMPLEMENTED` |
| Token 权限被扩大 | 权限合同 CI 与负向 403 探针阻止/发现越权 | `LIVE_ACCEPTED` |
| 子 Issue 已存在 | 按治理生成的唯一标题复用 | `LIVE_ACCEPTED` |
| 专家命令重复 | 首次命令去重；受控 retry 使用唯一 retry_id | `LIVE_ACCEPTED` |
| 子 Issue 创建但没有任何机器人活动 | 保护窗口后最多执行一次恢复；写入唯一 recovery marker | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| compute/API 事件丢失 | 子 Issue close 后 reopen 一次，重新触发 opened/reopened 工作流 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| expert 命令事件丢失 | 精确重发一次 `/run-expert-team <task_id>` | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 一次恢复仍无活动 | 最终超时或监控失败，不继续循环 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 子工作流已接受后被取消 | 不盲目并发重跑；等待超时并进入迟到对账 | `IMPLEMENTED/PARTIAL` |
| 子 Issue 被人工关闭 | 关闭不代表取消；治理继续依据可信评论对账 | `OPERATIONAL` |

恢复只在“没有任何可信 bot 活动”时触发。只要子中心已发布 ACCEPTED、REJECTED、FAILED 或 COMPLETED 等正式状态，治理不得再进行 lost-trigger 恢复。

## 六、轮询、超时与迟到结果

| 场景 | 当前处理 | 状态 |
|---|---|---|
| 单次 GitHub API 网络错误 | 继续轮询，成功后连续错误计数归零 | `IMPLEMENTED` |
| 连续 5 次轮询错误 | 返回 `CONTROL_MONITOR_ERROR`，不宣称业务失败或成功 | `IMPLEMENTED` |
| 达到 `wait_seconds` 无终态 | 返回 `CONTROL_TIMEOUT`；子 Issue 仍为权威执行位置 | `IMPLEMENTED` |
| 终态位于第 101–1000 条评论 | 统一分页读取最多 10 页，从最新评论倒序识别 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 迟到成功 | 定时对账器更新为 `CONTROL_RECONCILED_LATE_SUCCESS` | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 迟到失败 | 定时对账器更新为 `CONTROL_RECONCILED_LATE_FAILURE` | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 终态 Task ID 缺失或不匹配 | 返回 `CONTROL_CHILD_TASK_MISMATCH`，不得绑定结果 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| 成功终态缺 Artifact | 返回 `CONTROL_CHILD_EVIDENCE_INVALID`，不得发布成功 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` |
| GitHub 403/429 rate limit | 目前作为监控错误处理 | `P1_REQUIRED` |

迟到对账器与主 worker 使用同一全局 concurrency group，因此不会在业务任务执行时并发改写同一治理状态。

## 七、Artifact 与终态合同

### Compute 成功

必须同时存在：

```text
Task ID = 预期治理 Task ID
Artifact ID = 数字
Artifact digest = 64 位小写十六进制
Artifact URL 末尾 = /artifacts/<Artifact ID>
```

### Intelligence 成功或部分成功

`API_COMPLETED` 与 `API_PARTIAL` 均必须满足与 Compute 相同的 Artifact 身份合同。

### Expert 成功

必须同时存在：

```text
Task ID = 预期治理 Task ID
Primary Artifact ID / digest / URL
Final attestation Artifact ID / digest / URL
两个 URL 分别与对应 ID 一致
```

### 失败与拒绝

失败终态不要求成功 Artifact，但必须包含正确 Task ID。专家无效票据兜底拒绝链必须从正式命令提取 Task ID，模型调用保持 0。

## 八、GPT 交互规范

GPT 必须区分：

```text
CREATED      仅表示治理 Issue 创建成功
QUEUED       等待 FIFO
RUNNING      治理已锁定任务
DISPATCHED   子 Issue 已确认
ACCEPTED     子中心已受理
COMPLETED    可信终态和 Artifact 合同通过
FAILED       可信失败终态或治理故障
TIMEOUT      等待窗口结束，子任务可能仍在运行
RECONCILED   超时/监控错误后取得迟到可信终态
```

终态查询流程：

1. GET 治理 Issue；
2. GET 治理 Issue comments；
3. 只选择 `user.login == github-actions[bot]` 的评论；
4. 选择最新可信终态；
5. 核对 Task ID、route、child status 和 Artifact 身份；
6. 不得把用户编辑的 Issue body 单独作为最终证据。

GPT Action 仍只有三项操作：创建治理 Issue、读取治理 Issue、读取治理 Issue comments。没有 PATCH、PUT、DELETE，也没有子仓库、Contents、PR、Actions、Workflow 或 Secrets 接口。

## 九、子中心自身故障

### 情报中心

- 上游 HTTP 500/429/超时：结构化失败，不把“仓库连通”写成“数据成功”；
- HTTP 200 但无数据：由 connector contract 判断 `data_present`；
- 响应过大：票据字节限制、公开评论分块、完整证据进 Artifact；
- 上游可重试：只使用票据允许的有限 attempts。

### 计算中心

- 依赖安装、执行或 Artifact 失败：返回 `COMPUTE_FAILED`；
- 网络隔离失效：不得发布正式计算结果；
- 无上游证据时：结果只能保持实验或决策阻断状态。

### 专家中心

- 非法票据：在模型调用前返回 task-bound `EXECUTION_REJECTED`；
- 有效任务：只有审计、主 Artifact、独立复算、最终状态和 attestation 完整通过才能成功；
- main 与 production 不一致：生产工作流失败关闭。

## 十、安全和灾难恢复

| 场景 | 处理 |
|---|---|
| Key 泄露 | 立即 revoke；创建相同最小权限 Key；替换 Secret；审计泄露窗口内 Issues 和 Actions；重跑正向 Issues 与负向 403 探针 |
| 仓库重命名、转移或可见性变化 | 路由失效并返回派发错误；P1 增加每日仓库身份健康检查 |
| GitHub 平台长期故障 | 显式进入 `PLATFORM_UNAVAILABLE`；禁止无证据本地绕过；恢复后从开放治理 Issue 继续 |
| Artifact 过期 | 测试证据允许短期保留；关键生产结果需要长期归档策略 |
| 用户要求立即取消运行中任务 | 当前最小权限 Token 无 Actions write；只能取消排队任务，不能虚报已停止运行中的 workflow |

## 十一、优先级

### P0 候选实现状态

截至本版本，P0-01 至 P0-08 已进入候选生产代码并通过确定性测试：

1. 失败任务重新提交；
2. comments 全分页；
3. Task ID 强绑定；
4. Artifact/attestation 合同；
5. 迟到终态对账；
6. 一次性 lost-trigger 恢复；
7. GPT comments 只读操作；
8. JSON 复杂度、Secret 变体和执行字段防护。

在合并后的真实零调用验收完成前，整体状态保持：

```text
P0_IMPLEMENTED_PENDING_PRODUCTION_ACCEPTANCE
```

### P1

1. rate-limit 感知退避；
2. 下一 worker 唤醒有限重试；
3. Token scope 与仓库身份每日健康检查；
4. 统一用户状态词典及下一动作；
5. 长期 Issue/Artifact 归档策略。

### P2

1. 失败率、等待时间、超时率、队列长度统计；
2. 仅异常通知的每日零调用健康摘要；
3. 定期零费用混沌测试；
4. 故障演练和恢复时间记录。

## 十二、最终验收门槛

只有同时满足以下条件，才能写成“复杂使用条件下稳定”：

1. 至少 30 类异常均有明确终态；
2. 所有非法输入子派发为 0；
3. 所有 active/success duplicate 子派发为 0；
4. 历史失败任务可以生成新 Task ID 再次执行；
5. FIFO 在突发混合队列中保持；
6. 排队期和运行中篡改不能改变冻结任务；
7. 三中心终态 Issue 自动回收；
8. 迟到终态可自动对账；
9. 第 101–1000 条评论中的终态仍可发现；
10. Task ID、子 Issue、Artifact ID、digest、URL 一致；
11. 专家无效票据拒绝带 Task ID 且模型调用为 0；
12. Key 权限负向测试对代码、分支、PR、Workflow、Secrets 持续为 403；
13. 自定义 GPT 已导入新版 Action schema，并能读取可信 comments；
14. 所有测试和费用回执如实记录。

## 十三、当前结论

```text
最小权限与越权防护：LIVE_ACCEPTED
三中心正式派发：LIVE_ACCEPTED
FIFO 与突发队列：LIVE_ACCEPTED
输入攻击与运行中篡改防护：LIVE_ACCEPTED
三中心终态 Issue 自动回收：LIVE_ACCEPTED
P0-01 至 P0-08 代码：IMPLEMENTED
P0 确定性测试：PASSED
P0 合并后真实验收：PENDING
自定义 GPT 新 schema 导入：OPERATIONAL / PENDING
P1 与 P2：未作为本轮生产阻断
```

不得把 GitHub 平台级不可用、运行中 workflow 的即时取消、隐藏 PAT 配置反向读取或自定义 GPT schema 自动同步，描述成系统能够完全自动控制的能力。
