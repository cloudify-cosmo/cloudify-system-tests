import time

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.framework.util import set_client_tenant, get_resource_path

AGENT_OSES = [
    'centos_8',
    'rhel_8',
    'windows_2012',
]


def test_agent_retry(ssh_key, module_tmpdir, test_config, logger, request):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  len(AGENT_OSES) + 1)
    manager = hosts.instances[0]
    agent_vms = {}

    for idx, agent_os in enumerate(AGENT_OSES):
        hosts.instances[idx + 1] = VM(agent_os, test_config)
        agent_vms[agent_os] = hosts.instances[idx + 1]

    passed = True
    executions = {}

    try:
        hosts.create()

        # We could create these one at a time in the next loop, but this way
        # we still have them if we need to troubleshoot cross-contamination.
        examples = {
            agent_os: get_example_deployment(
                manager, ssh_key, logger, f'agent_retry_{agent_os}',
                test_config, vm=agent_vms[agent_os]
            )
            for agent_os in AGENT_OSES
        }

        for agent_os in AGENT_OSES:
            example = examples[agent_os]
            example.blueprint_file = get_resource_path(
                'blueprints/compute/triggered.yaml')
            vm = agent_vms[agent_os]
            tenant_name = f'agent_retry_{agent_os}'
            if 'windows' in agent_os:
                vm.wait_for_winrm()
                example.use_windows(vm.username, vm.password)
            else:
                example.inputs['path'] = '/tmp/test_file'

            example.upload_blueprint()
            example.create_deployment()

            logger.info('Starting install for %s', agent_os)
            with set_client_tenant(manager.client, tenant_name):
                executions[agent_os] = manager.client.executions.start(
                    example.deployment_id, 'install').id

        for agent_os in AGENT_OSES:
            example = examples[agent_os]
            trigger_path = example.inputs['path'] + '_trigger'
            wait_path = example.inputs['path'] + '_wait'
            vm = agent_vms[agent_os]
            start = time.time()
            max_delay = 60
            while True:
                if example.file_exists(wait_path):
                    logger.info('Wait file exists on %s. '
                                'Unplugging network cable ...',
                                agent_os)
                    manager.run_command(
                        f'iptables -I INPUT 1 -p tcp -s {vm.ip_address} '
                        '-j DROP',
                        use_sudo=True
                    )
                    vm.put_remote_file_content(trigger_path, '')
                    break
                else:
                    if time.time() - start > max_delay:
                        raise AssertionError(
                            f'Took more than {max_delay} seconds to create '
                            f'wait file for {agent_os}'
                        )
                    logger.info('Waiting for file creation on %s',
                                agent_os)
                    time.sleep(5)

        logger.info('Waiting to give time for failures to happen')
        time.sleep(10)

        logger.info('Plugging network cables back in')
        for agent_os in AGENT_OSES:
            # Yes, this is technically not necessarily doing it in order of
            # the specific agent OS it claims, but it'll be fine.
            manager.run_command('iptables -D INPUT 1', use_sudo=True)

        for agent_os in AGENT_OSES:
            # Give agent some time for the retry
            logger.info('Waiting for %s to finish install', agent_os)
            timeout, delay = 120, 15
            tenant = examples[agent_os].tenant
            while timeout > 0:
                with set_client_tenant(manager.client, tenant):
                    exc = manager.client.executions.get(executions[agent_os])

                logger.info('Execution state: %s' % exc.status)
                if exc.status == 'terminated':
                    break
                else:
                    time.sleep(delay)
                    timeout -= delay
            assert exc.status == 'terminated'

            logger.info('Checking runtime prop on %s', agent_os)
            with set_client_tenant(manager.client, tenant):
                node = manager.client.node_instances.list(
                    node_id='triggered')[0]
                assert node.runtime_properties['done']

            logger.info('Uninstalling %s', agent_os)
            examples[agent_os].uninstall()
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)
