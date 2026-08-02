# 安全边界

- 治理仓库不持有业务 API Key、模型 Key 或中心运行 Secret。
- 治理仓库当前唯一跨仓库控制 Secret 是 `CONTROL_PLANE_TOKEN`：细粒度 PAT，仅授权三个业务仓库 Issues 读写；不得授权 Contents 写入。
- GPT Action 使用独立细粒度 PAT，只授权治理仓库 Issues 读写；不得访问三个业务仓库。
- 业务 Secret 不跨仓库共享；优先使用仓库级或 Environment 级权限。
- 不使用 Git submodule、共享私有运行工作流、中心间直接调度或中心间 Artifact 下载。
- 数值计算运行面默认断网；文献证据运行面只允许明确白名单。
- 禁止票据提交任意 Python、Shell、概率模型、求解器代码、运行时插件安装或任何凭证字段。
- 控制平面只信任目标中心 `github-actions[bot]` 发布的正式终态；用户评论不能伪造完成。
- Server酱当前仅为禁用安装占位：不得配置 SendKey、网络端点、工作流钩子、发送器、消息格式、触发条件或重试策略，直到用户明确设计并批准。
