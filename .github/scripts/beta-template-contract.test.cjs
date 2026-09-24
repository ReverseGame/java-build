const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const yaml = require('js-yaml');

/** 解析公共工作流；入参为文件名，返回 YAML 对象用于发布契约校验。 */
function workflow(filename) {
    return yaml.load(readFileSync(path.join(__dirname, '../workflows', filename), 'utf8'));
}

const build = workflow('beta-maven-build.yml');
const api = workflow('beta-api-deploy.yml');

test('本地依赖默认复用，构建和 API 发布均不恢复或上传 Maven 云缓存', () => {
    for (const current of [build, api]) {
        assert.equal(current.on.workflow_call.inputs.useMavenCache.default, false);
        assert.equal(current.on.workflow_call.inputs.buildRunner.default, 'local-server');
        const job = Object.values(current.jobs)[0];
        const java = job.steps.find(step => step.uses?.startsWith('actions/setup-java@'));
        assert.ok(java.with.cache.includes('inputs.useMavenCache'));
        assert.ok(!job.steps.some(step => step.uses?.startsWith('actions/cache@')));
    }
});

test('两条镜像路径均关闭不兼容证明，并使用同一个固定后端与仓库缓存', () => {
    const job = build.jobs.java_reuse_build;
    assert.equal(job.env.BUILDX_NO_DEFAULT_ATTESTATIONS, '1');
    const builder = job.steps.find(step => step.id === 'buildx');
    assert.equal(builder.with.driver, 'docker-container');
    assert.equal(builder.with.version, 'v0.37.1');
    assert.equal(builder.with['driver-opts'], 'image=moby/buildkit:v0.33.0');
    assert.equal(builder.with['cache-binary'], false);
    const pushes = job.steps.filter(step => step.uses?.startsWith('docker/build-push-action@'));
    assert.equal(pushes.length, 2);
    for (const step of pushes) {
        assert.equal({...job.env, ...step.env}.BUILDX_NO_DEFAULT_ATTESTATIONS, '1');
        assert.ok(step.with.builder.includes('steps.buildx.outputs.name'));
        assert.equal(step.with['cache-to'], 'type=inline');
        assert.ok(step.with['cache-from'].includes('inputs.projectName'));
        assert.ok(step.with['cache-from'].includes('inputs.buildStage'));
        assert.ok(step.with.tags.includes('env.tag'));
        assert.ok(step.with.tags.includes('buildcache-v1'));
    }
});

test('部署标签可独立切换且保留就绪检查和不可变镜像标签', () => {
    const job = build.jobs.deploy_local;
    assert.equal(build.on.workflow_call.inputs.deployRunner.default, 'local-server');
    assert.ok(job['runs-on'].includes('inputs.deployRunner'));
    assert.equal(job.needs, 'java_reuse_build');
    assert.ok(job.env.tag.includes('github.sha'));
    assert.ok(!job.env.tag.includes('buildcache'));
    const rollout = job.steps.find(step => step.name === 'Wait for beta rollout');
    assert.ok(rollout.with.command.includes('rollout status'));
    assert.ok(rollout.with.command.includes('--timeout=300s'));
});

test('API 发布 Job 名与强制快照参数保持消费者等待协议兼容', () => {
    assert.deepEqual(Object.keys(api.jobs), ['deploy-api']);
    assert.equal(api.on.workflow_call.inputs.forceSnapshotDeploy.default, false);
    const change = api.jobs['deploy-api'].steps.find(step => step.id === 'change');
    assert.ok(change.env.FORCE_CHANGED.includes('inputs.forceSnapshotDeploy'));
    assert.ok(api.jobs['deploy-api']['timeout-minutes'] > 0);
});
