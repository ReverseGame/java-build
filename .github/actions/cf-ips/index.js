const cf_ips = require('@reverse_game/cf_ips')
const core = require('@actions/core')

async function run() {
    try {
        const input_ips = core.getInput('ips')
        let ips
        if (input_ips) {
            ips = input_ips
        } else {
            ips = await cf_ips.get_pool_ips_by_region(
                core.getInput('account_id', { required: true }),
                core.getInput('api_token', { required: true }),
                core.getInput('region', { required: true })
            )
        }
        core.info(`ips: ${ips}`)
        core.setOutput('ips', ips)
    } catch (err) {
        core.setFailed(err instanceof Error ? err.message : String(err))
    }
}

run()
