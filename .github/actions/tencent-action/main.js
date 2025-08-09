const tencent_cloud = require('@reverse_game/tencent_cloud')
const core = require('@actions/core')
async function run() {
    let action = core.getInput('action')
    if (action === 'create_image') {
        return await tencent_cloud.create_image(
            core.getInput('secret_id'),
            core.getInput('secret_key'),
            core.getInput('region'),
            core.getInput('instance_name_prefix')
        )
    } else if (action === 'get_ips') {
        return await tencent_cloud.get_ips(
            core.getInput('secret_id'),
            core.getInput('secret_key'),
            core.getInput('region'),
            core.getInput('instance_name_prefix')
        )
    } else if (action === 'create_image_sync_as') {
        return await tencent_cloud.create_image_sync_as(
            core.getInput('secret_id'),
            core.getInput('secret_key'),
            core.getInput('region'),
            core.getInput('instance_name_prefix'),
            core.getInput('launch_configuration_id')
        )
    }
}

run()