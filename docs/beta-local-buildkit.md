# beta 本地构建与仓库缓存模板

公共入口为 .github/workflows/beta-maven-build.yml 和 beta-api-deploy.yml。
候选分支：feat/ci-local-buildkit-cache-20260924-ycs。

## 输入与兼容

沿用 projectName、workDir、buildStage、projectPrefix、encrypt、dockerFile、mavenExtraArgs；
useMavenCache 默认 false。buildRunner、deployRunner 默认 local-server，部署专用实例准备好后可将 deployRunner 改为 local-deploy。
API 模板保留 apiModuleDir、forceSnapshotDeploy、javaVersion、awsRegion、s3Bucket，buildRunner 默认 local-server。
API job id 保持 deploy-api，兼容消费者按 deploy-api / deploy-api 等待的逻辑。

## 构建要求

调用方保留独立服务 workflow、API 依赖判断、pom 的 layered-image profile、Dockerfile.layered、Kubernetes 清单及 secrets 映射。
beta caller 设置 dockerFile: Dockerfile.layered、mavenExtraArgs: -Playered-image、useMavenCache: false。
模板中的 checkout 检出调用方代码，模板自身不依赖额外下载的本地脚本。

固定容器化 BuildKit；使用现有镜像仓库服务级环境标签的 inline 缓存。
关闭默认构建证明以兼容当前仓库；加密和非加密路径均适用。
部署引用提交 SHA 镜像标签；缓存标签只用于下次构建。首次没有缓存仍可正常构建。

## 发布与验证

候选阶段两个业务仓库引用本开发分支；稳定后发布版本并通过各仓库提交固定完整 SHA。
公共模板更新不会自动触发调用方流水线，需要在调用方手动运行或产生符合路径条件的提交。
验证冷缓存、资源增量、跨 Runner、加密/非加密、API 发布及 rollout；只比较同口径阶段耗时。
API 无变化时不强制重复发布；调用方仍负责对应 API 的发布条件和依赖等待。
已有非 beta 模板保持原状。回退修改调用方引用，不全局清理其他服务缓存。
