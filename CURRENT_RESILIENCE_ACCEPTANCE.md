# 当前韧性验收状态

版本：2026-08-05
治理版本：`4.2.1`

本文件是当前验收状态的人类可读快照。机制、故障处理和安全边界仍以 `RESILIENCE_AND_FAILURE_PLAYBOOK.md` 为准；机器状态以 `governance-resilience-matrix.json` 为准。预案中历史性的“候选、待验收、P1_REQUIRED”字样不得覆盖本文件和机器矩阵中的最新证据结论。

## P0 状态

| 项目 | 状态 | 当前证据 |
|---|---|---|
| P0-01 失败任务重新提交 | `LIVE_ACCEPTED` | 治理 #84 原样重提失败任务 #79，获得新 Task ID 和新子 Issue，没有被判为 duplicate。 |
| P0-02 评论分页 | `DETERMINISTIC_TESTED` | 最多读取 10 页、每页 100 条；未执行破坏性的 1000 评论真实 fixture。 |
| P0-03 Task ID 绑定 | `LIVE_ACCEPTED` | 治理 #84 忽略无 Task ID 的拒绝，只接受后续 `gov-84-expert` 的 task-bound 回执。 |
| P0-04 Artifact 合同 | `LIVE_ACCEPTED` | Compute #78/#88 和 Intelligence #90 均以 Task ID、Artifact ID、64 位 digest 和匹配 URL 完成。 |
| P0-05 迟到终态对账 | `LIVE_ACCEPTED` | 治理 #90 从 `CONTROL_TIMEOUT` 自动升级为 `CONTROL_RECONCILED_LATE_SUCCESS`，保留 Intelligence #961 的 Artifact `8906242150`。 |
| P0-06 lost-trigger 恢复 | `LIVE_ACCEPTED` | 治理 #88 对 Compute #109 只执行一次 `Recovery attempt 1/1`，子任务完成后自动对账为迟到成功。 |
| P0-07 GPT 可信评论读取 | `OPERATIONAL` | 仓库 OpenAPI 与权限合同通过；现有自定义 GPT 仍需人工导入新版 Action schema。 |
| P0-08 JSON、Secret 和执行字段防护 | `LIVE_ACCEPTED` | 治理 #80 拒绝 `clientSecret`、`pythonCode`，子派发及调用均为 0。 |

## P1 状态

P1 已合并到治理 `main`，合并提交为 `85afeb103a6d6875748a88f7dfd85b8835b72626`。成功终态优先级热修复随后以提交 `6175a5e31742c389e750081653a8372a87be01e7` 合并。

| 项目 | 状态 | 说明 |
|---|---|---|
| GitHub 限流与网络退避 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` | 有限重试 429、rate-limit 403、502/503/504 和短时网络错误；普通 403/4xx 不重试。 |
| 下一 FIFO worker 唤醒 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` | 0、5、15 秒三次尝试；失败发布 `CONTROL_QUEUE_WAKE_DEGRADED`，15 分钟 schedule 兜底。 |
| 每日 Token/仓库健康检查 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` + `OPERATIONAL` | 验证四仓身份、Issue 正向权限及 Contents/Actions Secrets 负向权限；只有异常才维护一个健康 Issue。 |
| 状态词典 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` | 为控制、失败、超时、迟到对账、队列降级和平台不可用定义终态性、用户含义和下一动作。 |
| Issue/Artifact 保留策略 | `IMPLEMENTED` + `DETERMINISTIC_TESTED` + `OPERATIONAL` | Issue 作为长期任务索引；GitHub Artifact 有限期，长期归档需单独配置。 |

## 吸收成功规则

对同一 Task ID，只要存在由 `github-actions[bot]` 发布、Task ID 正确且 Artifact 合同完整的成功终态，该成功就是吸收终态。后续由 reopen、重复受理、already-running、replay 或幂等保护产生的拒绝，不能撤销已完成成功。

治理 #90 的真实验收覆盖了该顺序：

```text
API_COMPLETED + 完整 Artifact
→ 后续 API_REJECTED: already accepted or running
→ 治理仍选择 API_COMPLETED
→ CONTROL_RECONCILED_LATE_SUCCESS
```

## 仍然存在的边界

1. P0-02 只有确定性分页测试，没有执行 1000 条评论的破坏性真实 fixture。
2. 自定义 GPT 不会自动导入仓库中的新版 OpenAPI；P0-07 需要人工更新 GPT Action schema。
3. GitHub 平台级故障无法在不破坏证据架构的情况下绕过。
4. 最小权限 `CONTROL_PLANE_TOKEN` 没有 Actions write，关闭 Issue 不代表取消已经运行的 workflow。
5. 隐藏的 fine-grained PAT 勾选项无法通过仓库 API 反向读取；运行时正向和负向权限测试是可执行证据。
6. GitHub Artifact 不是无限期档案。

## 费用与调用

本轮 P0/P1 韧性整改、异常 fixture 和权限验收没有触发付费模型调用。P0-05 的 Intelligence fixture 使用公开 Open-Meteo elevation 请求一次；P0-06 的 Compute fixture保持模型调用 0、外部数据请求 0。
