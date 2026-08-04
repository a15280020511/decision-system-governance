# 计算中心基准库存储网关

本目录是私有 Hugging Face Dataset `compute-numeric-baselines` 的唯一控制入口。它属于治理仓库控制平面，不是第四个业务中心，也不执行情报采集、计算或专家研判。

## 固定职责

```text
网页 GPTs
  → 治理仓库 Issue
    → 情报中心采集、清洗、数值化
      → 不可变纯数值 Artifact
        → 治理仓库核验并写入私有基准库
          → 治理仓库按任务构建转交包
            → 断网计算中心
```

- 情报中心只产出纯数值 Parquet 与 GitHub Artifact，不持有 `HF_TOKEN`，不直接读写私有 Dataset。
- 治理仓库独占 `HF_TOKEN`、基准库仓库变量和跨仓库 Artifact 只读凭据。
- 计算中心保持 `network=deny`，不得直连 Hugging Face；只接受治理仓库转交的任务级数据包。
- 专家中心不得访问基准库。
- 三个业务仓库之间禁止直接通信。
- 网页 GPTs 只连接治理仓库，不直接连接三个业务仓库或 Hugging Face。

## 数据边界

Hugging Face 私有 Dataset 只允许：

- Parquet；
- 整数和浮点列；
- 无空值；
- 固定表名；
- ZSTD 压缩；
- 治理网关核验后的追加批次或完整快照。

禁止上传：

- 网页正文、PDF、文献全文、摘要和自然语言报告；
- JSON 控制文件和 Secret；
- 知识库或知识图谱；
- 患者级、受监管或未经授权的数据。

## 治理 Issue

标题固定为：

```text
[baseline]
```

健康检查：

```json
{
  "schema_version": "governance-baseline-ticket-v1",
  "operation": "health"
}
```

入库：

```json
{
  "schema_version": "governance-baseline-ticket-v1",
  "operation": "ingest_evidence_artifact",
  "source_run_id": 123456789,
  "artifact_name": "compute-baseline-export-123-123456789",
  "expected_manifest_sha256": "<64位小写SHA-256>"
}
```

来源仓库被固定为 `a15280020511/evidence-data-center`，不能通过票据改写。

## Secret 与变量

仅在治理仓库配置：

- `HF_TOKEN`：只允许访问对应私有 Dataset；
- `BASELINE_TRANSFER_TOKEN`：只允许读取情报中心 Actions Artifact；
- `HF_NUMERIC_BASELINE_DATASET_REPO`：可选，默认当前 Hugging Face 用户下的 `compute-numeric-baselines`。

情报、计算和专家仓库不得保存上述 Hugging Face 写入凭据。
