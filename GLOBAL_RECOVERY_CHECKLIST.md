# 全局恢复清单

- [ ] 确认三个业务仓库的默认分支和最后可信提交。
- [ ] 核验 `INTERFACE_VERSION_MATRIX.json`。
- [ ] 核验能力目录、接口合同和 SHA。
- [ ] 核验各仓库所需 Secret 名称已重新配置，但不读取或导出值。
- [ ] 对每个中心分别运行无费用 dry-run / mock 验收。
- [ ] 仅在单中心通过后恢复 GPTs 对该中心的入口。
- [ ] 最后运行一条跨中心串行影子 Pipeline，核验总 Manifest。
