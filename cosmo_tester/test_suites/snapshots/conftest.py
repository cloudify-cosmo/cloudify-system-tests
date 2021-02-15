import pytest

from cosmo_tester.framework.test_hosts import Hosts, get_image
from cosmo_tester.test_suites.snapshots import get_multi_tenant_versions_list


@pytest.fixture(scope='function', params=get_multi_tenant_versions_list())
def hosts(request, ssh_key, module_tmpdir, test_config, logger):
    hosts = Hosts(
        ssh_key, module_tmpdir,
        test_config, logger, request,
        number_of_instances=4,
    )

    hosts.instances[0] = get_image(request.param, test_config)
    hosts.instances[1] = get_image('master', test_config)
    hosts.instances[2] = get_image('centos', test_config)
    hosts.instances[3] = get_image('centos', test_config)

    win_vm = hosts.instances[2]
    win_vm.prepare_for_windows('windows_2012')

    lin_vm = hosts.instances[3]
    lin_vm.image_name = test_config.platform['centos_7_image']
    lin_vm.username = test_config['test_os_usernames']['centos_7']

    hosts.create()

    try:
        if request.param in ['5.0.5', '5.1.0']:
            old_mgr = hosts.instances[0]
            old_mgr.wait_for_manager()
            old_mgr.run_command('mv /etc/cloudify/ssl/rabbitmq{_,-}cert.pem',
                                use_sudo=True)
            old_mgr.run_command('mv /etc/cloudify/ssl/rabbitmq{_,-}key.pem',
                                use_sudo=True)
            old_mgr.run_command(
                'chown rabbitmq. /etc/cloudify/ssl/rabbitmq-*', use_sudo=True)
            old_mgr.run_command('systemctl restart cloudify-rabbitmq',
                                use_sudo=True)
        yield hosts
    finally:
        hosts.destroy()
