# 三中心决策系统总体架构

```text
网页 GPTs 总控使用台
└── Decision System Governance（唯一控制平面，不是第四个业务中心）
    ├── Evidence & Data Center（采集、取证、清洗、数值化）
    ├── Computation & Simulation Center（断网计算、仿真、建模）
    └── Expert Assessment Center（无工具专家研判）

Decision System Governance
└── Compute Baseline Gateway
    └── Hugging Face private Dataset: compute-numeric-baselines
```

## 唯一入口

网页 GPTs 只连接 `a15280020511/decision-system-governance`，只通过治理仓库的受控 Issue 网关提交、查询和核验任务。GPTs 不得直接连接三个业务仓库，不得直接连接 Hugging Face，也不得直接读取或写入业务 Artifact。

治理仓库代表 GPTs 创建目标中心正式 Issue、轮询由 `github-actions[bot]` 发布的可信状态、核验终态并集中写回治理 Issue。三个业务仓库平行、并列、隔离，任何业务中心不得直接调用、调度、读取或下载另一个业务中心的运行结果。

## 计算基准库专用例外

治理仓库仍不执行情报采集、数值计算或专家研判，但它承担一项严格限定的基础设施职责：作为计算中心私有纯数值基准库的唯一存储网关。

```text
情报中心采集公开信息
→ 清洗、编码、单位统一、质量验证
→ 生成不可变纯数值 Parquet Artifact
→ 治理仓库下载并核验来源、Manifest、SHA、Schema、类型和空值
→ 治理仓库写入私有 compute-numeric-baselines
→ 治理仓库按具体计算任务生成受控转交包
→ 计算中心在网络隔离前取得转交包并断网执行
```

该例外只允许治理仓库：

1. 使用只读跨仓库凭据下载情报中心明确发布的基准库 Artifact；
2. 核验纯数值 Parquet；
3. 使用治理仓库独占的 `HF_TOKEN` 写入私有 `compute-numeric-baselines`；
4. 为计算任务构建不可变、带哈希的治理转交包。

该例外不允许治理仓库执行网页采集、数据解释、模型推理、数值计算、专家分析或修改业务结论。

## 基准库边界

Hugging Face 私有 Dataset 是计算中心的外部基准库，不是情报中心知识库，也不是通用文件仓库。只允许纯数值 Parquet；禁止网页正文、PDF、自然语言说明、知识库、知识图谱、控制 JSON、Secret、患者级数据和受控内容。

情报中心、计算中心和专家中心均不得持有私有 Dataset 的写入凭据。计算中心保持 `network=deny`，不得直连 Hugging Face。专家中心不得访问基准库。

## 权限分层

```text
GPT Action Token
  └─ 仅治理仓库 Issues 读写

治理仓库 GITHUB_TOKEN
  └─ 本仓库内容读取、Issue 回执和本仓库 Artifact

CONTROL_PLANE_TOKEN
  └─ 三个业务仓库 Issues 读写
     不授予 Contents 写入，不持有业务 API/模型 Secret

BASELINE_TRANSFER_TOKEN
  └─ 仅情报中心 Actions Artifact 读取
     不授予业务 Contents 写入、Issue 写入或 Secret 管理

HF_TOKEN
  └─ 仅治理仓库使用
     仅访问指定私有 compute-numeric-baselines Dataset
```

机器权威拓扑见 `control-plane/topology-contract.json`，基准库存储合同见 `compute-baseline-gateway/gateway-contract.json`。
