# 安全边界

## GPTs

- GPT Action 使用独立细粒度凭据，只授权治理仓库 Issues 读写。
- GPTs 不得直接访问三个业务仓库、Hugging Face、业务 Artifact、Secrets、Actions 写权限或仓库 Contents 写权限。

## 治理仓库

治理仓库不得持有业务采集 API Key、专家模型凭据或业务中心运行 Secret。仅允许下列治理基础设施凭据：

1. `CONTROL_PLANE_TOKEN`：仅三个业务仓库 Issues 读写；不得授权 Contents 写入。
2. `BASELINE_TRANSFER_TOKEN`：仅情报中心 Actions/Artifacts 读取；不得授权业务 Contents 写入或 Issue 写入。
3. `HF_TOKEN`：仅访问明确列出的受管 Hugging Face 仓库：私有 `compute-numeric-baselines` Dataset、私有 `evaluation-results` Dataset、私有 `managed-model-registry` Model Repository，以及公共静态 `decision-system-readonly-status` Space；不得访问模型推理、训练、Jobs、动态 Space 后端或其他私人仓库。
4. `OPENROUTER_API_KEY`：仅用于治理辅助模型目录核验和经批准的治理辅助任务；不得接收业务 Secret、私有基准数据、未脱敏日志或三个业务中心的私密载荷。
5. `SERVERCHAN_SENDKEY`：仅用于治理中心元数据告警；不得进入 Issue、Artifact、日志、通知正文或命令输出。
6. `HEALTHCHECKS_PING_URL`：可选外部失联检测地址；只允许发送 start、success、fail 信号，不得附带业务数据、日志或 Secret。

GitHub Actions 自动生成的 `GITHUB_TOKEN` 必须按工作流声明最小权限，不作为长期仓库 Secret。OSV.dev、deps.dev 和 CISA KEV 只允许无 Key、只读调用。

下列治理仓库 Variables 保存固定目标仓库 ID，不得由票据覆盖：

- `HF_NUMERIC_BASELINE_DATASET_REPO`
- `HF_EVALUATION_RESULTS_DATASET_REPO`
- `HF_MANAGED_MODEL_REPO`
- `HF_READONLY_SPACE_REPO`

治理仓库对业务 Artifact 的读取仅限 `compute-baseline-gateway`，来源仓库固定为 `a15280020511/evidence-data-center`，Artifact 名称必须使用固定前缀，且必须通过 Manifest、SHA-256、路径、大小、Parquet Schema、纯数值类型和空值验证。

## Hugging Face 受管资产

- `compute-numeric-baselines` 只允许纯数值 Parquet，由 `compute-baseline-gateway` 独立管理。
- `evaluation-results` 只允许结构化、脱敏的模型、数据、流水线和计算操作评测摘要；禁止原始提示词、原始模型输入输出、业务记录、个人数据、Secret 和未脱敏日志。
- `managed-model-registry` 初始化阶段只允许模型卡和版本登记；模型权重、适配器或其他二进制资产必须另行建立不可变 Artifact、摘要验证和审批合同，禁止自动复制公共模型。
- `decision-system-readonly-status` 必须为公共静态 Space，只能使用 `static` SDK；禁止生产控制、写操作、动态后端、模型推理、业务数据和 Secret。
- 三个业务中心不得持有 `HF_TOKEN`，不得直接读取或写入任何私有 Hugging Face 仓库。

## 通知与外部存活检测

- Server酱通知仅允许 repository、workflow、conclusion、Run ID、缩短 Commit SHA 和 Run URL。
- 禁止发送 Issue 正文、Artifact 内容、日志、提示词、模型输入输出、业务数据、个人数据和任何凭据值。
- SendKey 前缀必须由发送器校验；发送器不得打印完整端点。
- Server酱只监听明确列出的关键治理工作流，禁止递归监听自身。
- Healthchecks 心跳未配置时必须显式报告 `pending_secret`，不得伪报外部监控已启用。
- 外部心跳仅验证治理仓库 GitHub API 可达性，不读取三个业务仓库内容。

## 供应链审计

- OSV.dev 仅接收公开软件包生态、名称和锁定版本。
- deps.dev 仅接收公开软件包名称和锁定版本。
- CISA KEV 目录只下载到 Runner 本地并按 CVE 标识符关联。
- 禁止向上述服务提交源码、Artifact、提示词、业务数据、个人数据或 Secret。
- 默认仅报告；只有单独批准的策略才能把 KEV 命中升级为阻断门。

## 日志与诊断

- 统一诊断器只读取本仓库 GitHub Actions 元数据和失败日志。
- 下载日志后必须先脱敏，再进入 Artifact；原始日志 ZIP 不得保留。
- 禁止收集完整环境变量。
- 诊断包必须包含 Run/Job/Step 关联、失败分类、失败指纹、Manifest 和 SHA-256。
- Pull Request 验证阶段不签发 Attestation；定时或手动正式运行才生成来源证明。

## 业务仓库

- 情报中心不得配置或引用私有基准库或其他私有 Hugging Face 仓库写入所需的 `HF_TOKEN` 和相关私有仓库变量；它只上传不可变纯数值 Artifact，并匿名只读访问公开 Hugging Face Hub 目录。
- 计算中心不得配置 `HF_TOKEN`，保持 `network=deny`，只接收治理仓库转交的数据包。
- 专家中心不得配置 `HF_TOKEN`，继续禁止工具和网络。
- 三个业务中心不得直接通信、直接读取对方 Artifact 或共享 Secret。
- 业务仓库中的统一诊断工作流是独立运维面，不赋予业务运行时跨中心通信、模型工具或额外网络能力。

## 数据载荷

- 计算基准库只允许纯数值 Parquet；禁止字符串、对象、列表、控制 JSON、正文、PDF、知识库、知识图谱和 Secret。
- 禁止票据提交任意 Python、Shell、概率模型、求解器代码、运行时插件安装、外部下载 URL 或任何凭证字段。
- 控制平面只信任目标中心 `github-actions[bot]` 发布的正式终态；用户评论不能伪造完成。
- 计算基准入库批次必须有唯一 `batch_id`；重复批次必须拒绝。
- Dataset 必须保持 private；出现任何意外非 Parquet 文件时阻断写入。
