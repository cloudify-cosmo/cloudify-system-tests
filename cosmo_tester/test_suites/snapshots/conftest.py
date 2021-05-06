import pytest

from cosmo_tester.framework.test_hosts import Hosts, VM
from cosmo_tester.test_suites.snapshots import get_multi_tenant_versions_list


@pytest.fixture(scope='function', params=get_multi_tenant_versions_list())
def hosts(request, ssh_key, module_tmpdir, test_config, logger):
    hosts = Hosts(
        ssh_key, module_tmpdir,
        test_config, logger, request,
        number_of_instances=4,
    )

    hosts.instances[0] = VM(request.param, test_config)
    hosts.instances[1] = VM('master', test_config)
    hosts.instances[2] = VM('windows_2012', test_config)
    hosts.instances[3] = VM('centos_7', test_config)

    hosts.create()

    try:
        if request.param in ['5.0.5', '5.1.0']:
            old_mgr = hosts.instances[0]
            old_mgr.wait_for_manager()
            # This is inconsistent in places, so let's cope with pre-fixed...
            old_mgr.run_command('mv /etc/cloudify/ssl/rabbitmq{_,-}cert.pem',
                                use_sudo=True, warn_only=True)
            old_mgr.run_command('mv /etc/cloudify/ssl/rabbitmq{_,-}key.pem',
                                use_sudo=True, warn_only=True)
            # ...and then validate that the fix is in.
            old_mgr.run_command('test -f /etc/cloudify/ssl/rabbitmq-cert.pem')
            old_mgr.run_command('test -f /etc/cloudify/ssl/rabbitmq-key.pem')
            old_mgr.run_command(
                'chown rabbitmq. /etc/cloudify/ssl/rabbitmq-*', use_sudo=True)
            old_mgr.run_command('systemctl restart cloudify-rabbitmq',
                                use_sudo=True)
        yield hosts
    finally:
        hosts.destroy()
