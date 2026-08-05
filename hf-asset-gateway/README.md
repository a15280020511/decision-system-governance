# Hugging Face 受管资产网关

治理仓库统一管理三个补充资产：

1. 私有 `evaluation-results` Dataset：保存结构化、脱敏、可版本化的模型、数据、流水线和计算操作评测摘要；
2. 私有 `managed-model-registry` Model Repository：保存模型卡、版本登记和经单独批准的自有模型或适配器；
3. 公共静态 `decision-system-readonly-status` Space：仅做非关键只读展示和原型验证。

现有私有 `compute-numeric-baselines` Dataset 继续由 `compute-baseline-gateway` 独立管理，不与本目录合并。

## 运行边界

- `HF_TOKEN` 只能访问明确列出的四个受管仓库；
- 禁止模型推理、训练、Jobs 和动态 Space 后端；
- Space 只能使用 `static` SDK，不具备写操作或生产控制能力；
- 评测库禁止原始提示词、原始模型输入输出、业务数据、个人数据、Secret 和未脱敏日志；
- 模型仓库初始化后仍禁止二进制模型资产自动上传，后续必须单独建立 Artifact、摘要和审批合同；
- 三个业务中心不得持有 `HF_TOKEN` 或直接访问这些私有仓库。

## GitHub 配置

Secret：

```text
HF_TOKEN
```

可选 Repository Variables：

```text
HF_EVALUATION_RESULTS_DATASET_REPO=<HF账号>/evaluation-results
HF_MANAGED_MODEL_REPO=<HF账号>/managed-model-registry
HF_READONLY_SPACE_REPO=<HF账号>/decision-system-readonly-status
```

未配置变量时，网关会根据 `HF_TOKEN` 对应账号使用上述默认仓库名。

## 票据

标题必须为：

```text
[hf-assets]
```

初始化：

```json
{
  "schema_version": "governance-hf-assets-ticket-v1",
  "operation": "bootstrap"
}
```

健康检查：

```json
{
  "schema_version": "governance-hf-assets-ticket-v1",
  "operation": "health"
}
```

票据只能由仓库所有者提交。工作流会生成安全回执和 GitHub Actions Artifact。
