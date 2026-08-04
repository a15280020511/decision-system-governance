# 安全边界

## GPTs

- GPT Action 使用独立细粒度凭据，只授权治理仓库 Issues 读写。
- GPTs 不得直接访问三个业务仓库、Hugging Face、业务 Artifact、Secrets、Actions 写权限或仓库 Contents 写权限。

## 治理仓库

治理仓库不得持有业务采集 API Key、模型 Key、专家模型凭据或业务中心运行 Secret。仅允许以下三个基础设施凭据：

1. `CONTROL_PLANE_TOKEN`：仅三个业务仓库 Issues 读写；不得授权 Contents 写入。
2. `BASELINE_TRANSFER_TOKEN`：仅情报中心 Actions/Artifacts 读取；不得授权业务 Contents 写入或 Issue 写入。
3. `HF_TOKEN`：仅访问指定私有 `compute-numeric-baselines` Dataset；不得访问模型推理、训练、Spaces 或其他私人仓库。

`HF_NUMERIC_BASELINE_DATASET_REPO` 作为治理仓库变量保存目标 Dataset ID，不得由票据覆盖。

治理仓库对业务 Artifact 的读取仅限 `compute-baseline-gateway`，来源仓库固定为 `a15280020511/evidence-data-center`，Artifact 名称必须使用固定前缀，且必须通过 Manifest、SHA-256、路径、大小、Parquet Schema、纯数值类型和空值验证。

## 业务仓库

- 情报中心不得配置或引用私有基准库写入所需的 `HF_TOKEN` 和相关私有 Dataset 变量；它只上传不可变纯数值 Artifact。
- 计算中心不得配置 `HF_TOKEN`，保持 `network=deny`，只接收治理仓库转交的数据包。
- 专家中心不得配置 `HF_TOKEN`，继续禁止工具和网络。
- 三个业务中心不得直接通信、直接读取对方 Artifact 或共享 Secret。

## 数据载荷

- 计算基准库只允许纯数值 Parquet；禁止字符串、对象、列表、控制 JSON、正文、PDF、知识库、知识图谱和 Secret。
- 禁止票据提交任意 Python、Shell、概率模型、求解器代码、运行时插件安装、外部下载 URL 或任何凭证字段。
- 控制平面只信任目标中心 `github-actions[bot]` 发布的正式终态；用户评论不能伪造完成。
- 计算基准入库批次必须有唯一 `batch_id`；重复批次必须拒绝。
- Dataset 必须保持 private；出现任何意外非 Parquet 文件时阻断写入。

Server酱当前仅为禁用安装占位：不得配置 SendKey、网络端点、工作流钩子、发送器、消息格式、触发条件或重试策略，直到用户明确设计并批准。
