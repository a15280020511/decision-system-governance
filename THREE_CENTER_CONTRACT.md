# 三中心隔离合同

1. GPTs 是唯一控制与证据中继。
2. 中心间禁止直接 API 调用、`repository_dispatch`、运行时 Artifact 下载和包依赖。
3. 公共 Schema 采用冻结副本、语义版本和 SHA-256；业务运行时不得跨仓库读取治理仓库。
4. 每个业务仓库独立 CI、独立 Environment、独立 Secret、独立日志和 Artifact。
5. Workflow success 不等于业务完成；必须核验业务状态、正文、Manifest、Artifact 和 SHA。
6. 单 Pipeline 最多 6 阶段；同一中心最多 2 次；反馈循环最多 1 次；默认串行。
