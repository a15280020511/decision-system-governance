# Decision System Governance

本仓库是三中心决策系统的治理与控制平面仓库，不是第四个业务中心；不执行数据请求、数值计算或专家研判，不调用模型，不保存业务 Secret 或业务 Artifact。

## 业务仓库

- `a15280020511/evidence-data-center`
- `a15280020511/compute-simulation-center`
- `a15280020511/expert-assessment-center`

GPTs（Orchestration Console）通过本仓库的受控 Issue 网关派发任务。业务中心之间禁止直接通信、跨仓库运行时读取、共享业务 Secret、共享业务工作流和互取 Artifact。治理仓库只创建正式子 Issue、轮询受信任状态并集中写回治理回执，不替代任何中心的业务执行与审计。

## GPTs 控制入口

- GPT Action OpenAPI：`gpts-action/openapi.yaml`
- 控制票据 Schema：`control-plane/control-ticket.schema.json`
- 控制平面运行手册：`CONTROL_PLANE_RUNBOOK.md`
- GPTs 操作约束：`gpts-knowledge/GPTS_CONTROL_PLANE.md`
- Server酱安装占位：`integrations/serverchan/integration.json`

Server酱当前仅完成仓库登记，状态为 `installed / disabled / not_designed`，没有发送代码、Secret、端点或工作流。

## 权威文件

- `ARCHITECTURE.md`
- `THREE_CENTER_CONTRACT.md`
- `INTELLIGENCE_CENTER_COMPLIANCE_CONSTITUTION.md`
- `MASTER_OPERATIONS_RUNBOOK.md`
- `GPTS_REBUILD_GUIDE.md`
- `GLOBAL_RECOVERY_CHECKLIST.md`
- `SECURITY_BOUNDARIES.md`
- `INTERFACE_VERSION_MATRIX.json`
- `contracts/`
