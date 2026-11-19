# java-build

## Rust workspace 部署

`.github/workflows/rust-workspace-template.yml` 的可选输入 `applyOnlyWhenMissing`
默认为 `false`，保持现有部署行为。调用方按需启用：

```yaml
with:
  applyOnlyWhenMissing: true
```

启用后，beta、普通生产和 EKS 部署遵循相同规则：

- 逐个查询清单中的 Deployment，只 apply 不存在的 Deployment；已存在的保留集群配置。
- 清单中的 ConfigMap、Service、HPA、Job 等非 Deployment 资源仍每次 apply。
- 所有查询成功后才 apply 筛选后的资源，再按原步骤通过 `set image` 更新目标服务镜像。
- 查询权限、网络等错误会终止部署，不会误判成首次部署；apply 和清单解析失败也会终止。
- 更新镜像后等待 `rollout status`，超时为 5 分钟。

已有服务的 requests/limits、副本数以集群为准；env、探针、挂载等 Deployment 配置变更
也不再随部署生效，需要手工 apply。混合清单中的 Deployment 会分别判断存在状态，
不会因为其中一个已存在而跳过其他缺失的 Deployment，或覆盖其他已有 Deployment。

本地模板自检需要 Linux、Python、PyYAML 和 Bash，在仓库根目录执行：

```shell
python .github/tests/test_rust_workspace_template.py
```

Windows 下使用 `wsl -e python3 .github/tests/test_rust_workspace_template.py`，
确保 WSL 中已安装 PyYAML；命令替身依赖 POSIX 可执行脚本。

自检使用假的 kubectl 和 AWS CLI，不连接集群、不触发部署。
