const tencent_cloud = require('@reverse_game/tencent_cloud')
const core = require('@actions/core')
async function run() {
    let action = core.getInput('action')
    if (action === 'create_image') {
        let image_id = await tencent_cloud.create_image(
            core.getInput('secret_id'),
            core.getInput('secret_key'),
            core.getInput('region'),
            core.getInput('instance_name_prefix')
        )
        core.setOutput('image_id', image_id)
    } else if (action === 'get_ips') {
        let ips = await tencent_cloud.get_ips(
            core.getInput('secret_id'),
            core.getInput('secret_key'),
            core.getInput('region'),
            core.getInput('instance_name_prefix')
        )
        core.setOutput('ips', ips)
    } else if (action === 'create_image_sync_as') {
        let image_id = await tencent_cloud.create_image_sync_as(
            core.getInput('secret_id'),
            core.getInput('secret_key'),
            core.getInput('region'),
            core.getInput('instance_name_prefix'),
            core.getInput('launch_configuration_id')
        )
        core.setOutput('image_id', image_id)
    }
}

run()