# java-build

## Rust workspace 部署

`.github/workflows/rust-workspace-template.yml` 的可选输入 `applyOnlyWhenMissing`
默认为 `false`，保持现有部署行为。调用方按需启用：

```yaml
with:
  applyOnlyWhenMissing: true
```

启用后，beta、普通生产和 EKS 部署遵循相同规则：

- 首次部署：查询 Deployment 确认不存在后，apply 原清单，再更新镜像。
- 已有服务：保留集群中的 Deployment 配置，只通过 `set image` 更新镜像；清单中的
  ConfigMap、Service、HPA、Job 等非 Deployment 资源仍每次 apply。
- 查询权限、网络等错误会终止部署，不会误判成首次部署；apply 和清单解析失败也会终止。
- 更新镜像后等待 `rollout status`，超时为 5 分钟。

已有服务的 requests/limits、副本数以集群为准；env、探针、挂载等 Deployment 配置变更
也不再随部署生效，需要手工 apply。此开关面向包含目标 Deployment 的清单，已有服务时
会过滤其中所有 Deployment；需要新增其他 Deployment 时，应单独部署。

本地模板自检需要 Python、PyYAML 和 Bash，在仓库根目录执行：

```shell
python .github/tests/test_rust_workspace_template.py
```

自检使用假的 kubectl 和 AWS CLI，不连接集群、不触发部署。
