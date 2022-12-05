from cosmo_tester.framework.test_hosts import Hosts, VM


# Agent OSes to test
AGENT_OSES = [
    'centos_8',
    'rhel_8',
    'windows_2012',
]


def get_test_prerequisites(ssh_key, module_tmpdir, test_config, logger,
                           request, vm_os, manager_count=1):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request,
                  manager_count + 1)
    hosts.instances[-1] = VM(vm_os, test_config)
    vm = hosts.instances[-1]

    return hosts, vm.username, vm.password


def validate_agent(manager, example, test_config,
                   broken_system=False, install_method='remote',
                   upgrade=False):
    agents = list(manager.client.agents.list(tenant_name=example.tenant,
                                             _all_tenants=True))
    instances = list(
        manager.client.node_instances.list(
            tenant_name=example.tenant, node_id='vm',
            _all_tenants=True
        )
    )

    assert len(agents) == 1
    assert len(instances) == 1

    agent = agents[0]
    instance = instances[0]

    if broken_system:
        expected_system = None
    else:
        expected_system = example.example_host.get_distro()
        if example.tenant.endswith('centos_8'):
            # Yes, we manage to get different behaviour for this OS
            expected_system = 'centos 8'

    expected_agent = {
        'ip': example.inputs.get('server_ip', '127.0.0.1'),
        'install_method': install_method,
        'tenant_name': example.tenant,
        'system': expected_system,
        'id': instance['host_id'],
        'host_id': instance['host_id'],
        'version': test_config['testing_version'].replace('-ga', ''),
        'node': instance['node_id'],
        'deployment': instance['deployment_id'],
    }

    if upgrade:
        # Because it gets a UUID tacked onto the end
        agent['id'] = agent['id'][:len(expected_agent['id'])]

    assert agent == expected_agent
