# 模型编排与治理辅助政策

状态：生产候选政策

## 结论

网页 GPT 是整个决策系统唯一的语义总控、唯一对外入口和三个业务中心之间的唯一中继。

`decision-system-governance` 是确定性政策、接口合同、版本矩阵、验收门和恢复规则的权威来源。治理仓允许部署一个无权治理副驾驶，但模型选择、真实付费 Canary 和日常治理推理必须严格分层。

当前允许的生产候选链路：

```text
OpenRouter只读目录与基准
→ 识别付费通用旗舰集合
→ 按明确治理任务Token画像计算预计实际费用
→ 选择预计费用最低的旗舰
→ 专用工作流执行一次真实付费Canary
→ 结构化结果与安全边界验收
```

在付费 Canary、正式 PR 和仓库保护门全部通过前，普通治理任务不得调用模型。

始终禁止：

```text
模型直接修改仓库
模型直接派发三个中心
模型自动合并、发布或回滚
模型修改Secret或顶层宪法
模型自主循环、互评循环或后台常驻
```

## 角色边界

### 网页 GPT

- 唯一理解用户目标、拆解任务和决定调用顺序的语义控制面；
- 唯一分别与治理仓库及三个业务中心通信的上层入口；
- 负责将自然语言转换为固定票据；
- 负责核对 Issue、Actions、哈希、Artifact 和生产门；
- 决定是否采纳治理副驾驶建议；
- 负责最终向用户解释结果；
- 不得绕过确定性门禁声明生产通过。

### 治理仓库

保存并执行：

- 总体架构和三中心隔离合同；
- 票据与跨仓库接口 Schema；
- 版本矩阵和冻结基线；
- 安全边界、验收标准、恢复与回滚手册；
- 顶层宪法及其确定性检查规则；
- OpenRouter 旗舰选择器、任务成本排序器、Canary合同及审计回执。

治理仓不成为第四个业务中心，不在业务运行时直接连接情报中心、计算中心或专家中心，也不通过 `repository_dispatch`、共享运行工作流或后台服务绕过既有控制面。

## 第一层：OpenRouter旗舰选择器

选择器只允许使用：

```text
GET https://openrouter.ai/api/v1/models
GET https://openrouter.ai/api/v1/benchmarks
```

选择器只读取：

- 模型标识和产品层级；
- 实时价格与生命周期；
- 输入输出模态；
- Intelligence、Coding、Agentic基准；
- 官方目录和基准元数据。

旗舰识别规则：

1. 排除免费、过期、Preview、Beta、Experimental；
2. 排除 Flash、Mini、Nano、Micro、Small、Lite、Fast、Instant、Turbo、Haiku 等经济或速度层级；
3. 排除 Coder、Code、Safety、Guard、Embedding、Rerank、Moderation 等领域专用型号；
4. 只保留付费、稳定、通用文本模型且三项基准完整；
5. 旗舰身份来自正式产品层级，或该公司实时能力分布中的自然最高层；
6. 选择器只形成旗舰集合，不以 OpenRouter 综合价格顺序作为最终成本结论。

选择器必须保持：

```text
模型调用：0
模型费用：0
仓库权限：contents: read
```

## 第二层：治理任务实际成本排序

任务成本排序器只消费旗舰选择器回执，不联网、不调用模型。

预计费用计算：

```text
预计费用
= 输入价 × 预计输入Token / 1,000,000
+ 输出价 × 预计输出Token / 1,000,000
+ 每请求固定费用
```

生产基准画像：

```json
{
  "expected_prompt_tokens": 10000,
  "expected_completion_tokens": 2000
}
```

该画像用于长期基准和周期健康检查；具体治理任务可以在票据中明确覆盖输入、输出 Token 预计值。禁止根据模型名称或公司修改成本公式。

排序规则：

1. 按预计单任务总费用升序；
2. 同费用时按输入单价升序；
3. 再按输出单价升序；
4. 再按综合能力分降序；
5. 最后按模型ID确定性排序。

缺失、负数、NaN、Infinity、重复模型、空旗舰集合或零总Token画像全部失败关闭。

## 第三层：真实付费Canary

真实付费Canary只允许在：

```text
.github/workflows/openrouter-governance-copilot-canary.yml
```

中执行，并必须满足：

- 从本次实时旗舰集合和任务成本排序结果读取第1名；
- 只调用 `POST /api/v1/chat/completions` 一次；
- 禁止网络重试和模型Fallback；
- 禁止工具、函数调用和仓库写权限；
- GitHub权限固定为 `contents: read`；
- 使用固定合成治理事故测试权限、Secret、无限循环和拓扑绕过；
- 输出固定JSON；
- 必须提出最小补丁、测试和回滚方案；
- 必须生成使用量、估算费用、模型ID和验证回执；
- Secret值不得进入日志、Artifact、提示词或模型输出。

Canary通过标准：

```text
verdict = REVISE
recommended_route = [decision-system-governance]
findings覆盖 permission、secret、loop、topology
最小补丁计划不少于3项
要求测试不少于3项
回滚计划不少于1项
model_calls = 1
fallback_model_calls = 0
repository_write_capability = false
tool_capability = false
secret_values_exposed = false
```

Canary失败时保持生产推理关闭，不切换模型、不重试、不沿用旧成功回执冒充新结果。

## Secret与权限

- 唯一允许的模型市场Secret名称为 `OPENROUTER_API_KEY`；
- Secret只存在于治理仓GitHub Actions Secrets；
- 禁止写入代码、日志、Artifact、Issue、PR或模型输入；
- 选择器、成本排序器和Canary工作流仓库权限固定为 `contents: read`；
- 禁止 `contents: write`、`issues: write`、`pull-requests: write`、`actions: write` 和 `id-token: write`；
- 只有专用Canary脚本可以包含推理端点；选择器目录必须持续禁止任何推理端点和POST请求。

## 治理副驾驶生产权限

通过Canary只证明候选模型具备最低治理辅助能力，不授予执行权。

治理副驾驶允许提供：

- 代码和Actions日志诊断；
- 最小补丁草案；
- 红队审阅；
- 路由建议；
- 测试和回滚建议；
- 治理合同冲突检查。

治理副驾驶始终禁止：

- 直接提交代码或修改分支；
- 合并PR、发布、回滚或修改Secret；
- 直接控制情报、计算或专家中心；
- 自主循环、模型互评循环或跨任务记忆；
- 替代Schema、测试、哈希、Artifact、人工授权和生产门；
- 与网页GPT共享最终决策权。

## 长期健康检查

- 代码或工作流变化时执行双Ubuntu版本离线回归和随机压力测试；
- 执行上游HTTP故障、权限和零推理边界测试；
- 每周执行一次OpenRouter只读实时目录和任务成本合同检查；
- 每次实时检查连续运行三次，验证旗舰集合、预计费用顺序、任务画像和最终模型一致；
- 周期检查只生成Actions回执和短期Artifact，不自动修改仓库或模型配置；
- 健康检查失败时保持上次生产配置不变，并将本次选择视为无效；
- 付费Canary不进入周期计划，只在模型资格首次建立或关键选择逻辑变更时执行。

## 固定调用链

```text
用户
→ 网页GPT（唯一语义总控与中继）
→ 治理仓只读旗舰选择器
→ 治理任务成本排序器
→ 独立真实付费Canary与生产门
→ 网页GPT决定是否采纳治理副驾驶建议
→ GitHub Actions确定性执行与审计
→ 网页GPT汇总回执并向用户解释
```

三个业务中心之间始终没有直接连接。

## 最终权责

- 用户：最终授权者；
- 网页GPT：唯一语义编排者、唯一中继和对外责任主体；
- GitHub Actions：唯一确定性执行与审计平台；
- 治理仓库：治理规则、选择器、成本排序器和验收门权威；
- OpenRouter旗舰选择器：只读、确定性、零推理；
- 任务成本排序器：离线、确定性、零推理；
- 治理副驾驶模型：通过Canary后仍然只是无权建议者。
