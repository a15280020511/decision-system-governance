# 三中心隔离合同

1. 网页 GPTs 是唯一外部业务编排者；治理仓库是 GPTs 的唯一命令、状态和数据转交网关，不是第四个业务中心。
2. GPTs 只能访问治理仓库，不得直接访问情报、计算、专家仓库或 Hugging Face。
3. 三个业务中心之间禁止直接 API 调用、`repository_dispatch`、运行时 Artifact 下载、共享 Secret、共享工作流、共享包依赖和结果互读。
4. 治理控制平面可以创建目标中心正式 Issue、读取可信终态、发布现有正式命令并集中写回治理回执。
5. 情报中心只负责公开信息采集、证据整理、清洗、编码、单位统一、质量验证和不可变数值 Artifact 生成；不得直接读写私有计算基准 Dataset。
6. 治理仓库是私有 `compute-numeric-baselines` 的唯一存储网关。它只可下载情报中心明确发布的基准 Artifact，核验 Manifest、SHA-256、Parquet Schema、数值类型、空值和来源后写入私有 Dataset。
7. 计算中心是基准库的唯一业务受益中心，但保持 `network=deny`，不得直连 Hugging Face；只能使用治理仓库按任务生成并转交的不可变数据包。
8. 专家中心禁止访问基准库、情报中心 Artifact 和计算中心 Artifact；专家中心继续禁止工具和网络。
9. 治理仓库不得执行网页采集、业务计算、仿真、模型推理、专家研判、业务结果修改或外部通知发送。基准网关只做确定性验证、存储和转交。
10. 基准库只允许纯数值 Parquet。禁止正文、PDF、摘要、知识库、知识图谱、控制 JSON、Secret、患者级数据、受控内容和任意可执行载荷。
11. 公共 Schema 采用冻结副本、语义版本和 SHA-256；业务运行时不得跨仓库读取另一个业务中心的控制文件。
12. 每个业务仓库保持独立 CI、Environment、日志和 Artifact；只有治理仓库拥有跨仓库控制和基准库存储所需的最小权限凭据。
13. Workflow success 不等于业务完成；必须核验业务状态、正文、Manifest、Artifact 和 SHA。
14. 单 Pipeline 最多 6 阶段；同一中心最多 2 次；反馈循环最多 1 次；默认串行。
15. `CONTROL_PLANE_TOKEN` 仅允许三个业务仓库 Issues 读写；`BASELINE_TRANSFER_TOKEN` 仅允许读取情报中心 Actions Artifact；`HF_TOKEN` 仅允许治理仓库访问指定私有计算基准 Dataset。
16. 任何票据不得包含 Secret、Authorization、Cookie、账户凭据、任意代码或任意外部 URL。基准来源仓库、Artifact 前缀和 Dataset 路径均由治理合同固定。
17. Server酱仍为 `installed / disabled / not_designed` 占位，不属于当前运行时。
