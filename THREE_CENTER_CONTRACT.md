# 三中心隔离合同

1. GPTs 是唯一业务编排者；治理仓库是 GPTs 的受控命令与状态网关，不是第四个业务中心。
2. 中心间禁止直接 API 调用、`repository_dispatch`、运行时 Artifact 下载和包依赖。
3. 治理控制平面只允许：创建目标中心正式 Issue、为专家票据发布现有正式命令、读取受信任 Issue 状态和写治理回执。
4. 治理控制平面不得执行数据请求、计算、专家研判、业务 Artifact 下载、业务结果修改或外部通知发送。
5. 公共 Schema 采用冻结副本、语义版本和 SHA-256；业务运行时不得跨仓库读取治理仓库。
6. 每个业务仓库独立 CI、独立 Environment、独立 Secret、独立日志和 Artifact。
7. Workflow success 不等于业务完成；必须核验业务状态、正文、Manifest、Artifact 和 SHA。
8. 单 Pipeline 最多 6 阶段；同一中心最多 2 次；反馈循环最多 1 次；默认串行。
9. `CONTROL_PLANE_TOKEN` 仅允许三个业务仓库 Issues 读写，不得拥有业务 Contents 写权限；任何业务 Secret 或未来通知凭证不得写入票据。
10. Server酱只以 `installed / disabled / not_designed` 占位登记，不属于当前运行时；其功能、权限、端点和通知规则由用户以后单独设计。
