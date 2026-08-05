# Decision System Governance

本仓库是三中心决策系统的唯一治理与控制平面，不是第四个业务中心。网页 GPTs 只能连接本仓库；情报、计算和专家三个业务仓库均由本仓库受控派发和核验。

## 业务仓库

- `a15280020511/evidence-data-center`
- `a15280020511/compute-simulation-center`
- `a15280020511/expert-assessment-center`

三个业务中心平行、隔离，禁止直接通信、调度、互读 Artifact、共享业务 Secret 或共享运行工作流。

## 唯一控制入口

- GPT Action OpenAPI：`gpts-action/openapi.yaml`
- 控制票据 Schema：`control-plane/control-ticket.schema.json`
- 控制平面运行手册：`CONTROL_PLANE_RUNBOOK.md`
- GPTs 操作约束：`gpts-knowledge/GPTS_CONTROL_PLANE.md`
- 机器拓扑合同：`control-plane/topology-contract.json`

GPTs 只拥有治理仓库 Issues 读写权限，不直接访问三个业务仓库、Hugging Face、分支、PR、Contents、Secrets 或业务 Artifact。

## 计算中心基准库

私有 Hugging Face Dataset `compute-numeric-baselines` 是计算中心外部纯数值基准库，其唯一存储网关位于：

- `compute-baseline-gateway/`
- `.github/workflows/compute-baseline-gateway.yml`

职责分工：

```text
情报中心：采集、清洗、数值化、验证、输出不可变纯数值 Artifact
治理仓库：核验 Artifact、写入私有基准库、构建计算转交包、审计
计算中心：接收治理转交包并断网计算
专家中心：不得访问基准库
```

情报、计算和专家仓库不得持有私有基准库的 `HF_TOKEN`。Hugging Face Dataset 只允许纯数值 Parquet，不得存放知识库、知识图谱、正文、PDF、自然语言材料、控制 JSON 或 Secret。

## 治理集成

- `integrations/serverchan/`：关键治理工作流失败的元数据通知，Secret 为 `SERVERCHAN_SENDKEY`。
- `integrations/osv/`：按公开软件包名称和锁定版本执行漏洞复核，无 Key、只读。
- `integrations/depsdev/`：读取依赖元数据、许可证和公告键，无 Key、只读。
- `integrations/cisa-kev/`：下载公开 KEV 目录并在 Runner 本地按 CVE 关联，无 Key、只读。
- `integrations/healthchecks/`：外部失联检测；实现已安装，配置 `HEALTHCHECKS_PING_URL` 后激活。

供应链审计入口：

- `.github/workflows/supply-chain-audit.yml`
- `tools/supply_chain_audit.py`

## 日志与自动诊断

四个仓库均使用统一的 `Workflow Diagnostic Sweep`。该工作流定时读取本仓库近期 Actions Run，对失败、取消、超时和启动失败运行下载完整日志，脱敏后生成：

```text
diagnostic-index.json
runs/<run_id>/run.json
runs/<run_id>/jobs.jsonl
runs/<run_id>/key-lines.jsonl
runs/<run_id>/failure.json
runs/<run_id>/redacted-logs/
manifest.json
summary.md
```

诊断器识别权限或 Secret、限流、超时、网络、依赖、Schema、Artifact、模型 Provider、测试、资源耗尽、运行时异常和未知错误，并输出失败 Step、失败指纹、重试建议和 SHA-256 Manifest。正式定时或手动诊断包生成 GitHub Artifact Attestation。

治理中心入口：

- `.github/workflows/diagnostic-sweep.yml`
- `tools/workflow_diagnostics.py`
- `DIAGNOSTICS_IMPLEMENTATION.md`

## 安全分析

- CodeQL：`.github/workflows/codeql.yml`
- Dependabot：`.github/dependabot.yml`
- 外部存活检测：`.github/workflows/governance-heartbeat.yml`
- Server酱失败告警：`.github/workflows/governance-failure-notify.yml`

所有外部通知和心跳只允许最小元数据，不得发送 Issue 正文、Artifact 内容、日志、提示词、业务数据、个人数据或 Secret。

## 权威文件

- `ARCHITECTURE.md`
- `THREE_CENTER_CONTRACT.md`
- `SECURITY_BOUNDARIES.md`
- `CAPABILITY_AUTHORITY_POLICY.md`
- `control-plane/topology-contract.json`
- `compute-baseline-gateway/gateway-contract.json`
- `MASTER_OPERATIONS_RUNBOOK.md`
- `GPTS_REBUILD_GUIDE.md`
- `GLOBAL_RECOVERY_CHECKLIST.md`
- `INTERFACE_VERSION_MATRIX.json`
- `contracts/`
