import pytest

from cosmo_tester.framework.deployment_update import (
    apply_and_check_deployment_update,
)
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    check_credentials,
    check_deployments,
    confirm_manager_empty,
    create_copy_and_restore_snapshot,
    get_manager_state,
    prepare_credentials_tests,
    set_client_tenant,
    SNAPSHOT_ID,
    stop_manager,
    upgrade_agents,
    verify_services_status,
)
from cosmo_tester.framework.util import get_resource_path


FROM_SOURCE_TENANT = 'from_source'
WIN_TENANT = 'default_tenant'
LIN_TENANT = 'lin_tenant'
NOINSTALL_TENANT = 'noinstall'

INSTALL_TENANTS = [FROM_SOURCE_TENANT, WIN_TENANT, LIN_TENANT]
TENANTS = [FROM_SOURCE_TENANT, WIN_TENANT, LIN_TENANT,
           NOINSTALL_TENANT]


def test_restore_snapshot_and_agents_upgrade_multitenant(
        hosts, logger, tmpdir, ssh_key, test_config):
    if not test_config['premium']:
        pytest.skip('Multi tenant snapshots are not valid for community.')

    new_manager, win_vm, lin_vm, old_manager_mappings = hosts

    old_versions = sorted(old_manager_mappings.keys())
    last_old_version = old_versions[-1]

    for old_ver in old_versions:
        old_mgr = old_manager_mappings[old_ver]
        if old_ver == '5.1.0':
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

        confirm_manager_empty(new_manager, logger)

        local_snapshot_path = str(tmpdir / 'snapshot-{}.zip'.format(old_ver))

        example_mappings = prepare_old_manager_resources(old_mgr, logger,
                                                         ssh_key, test_config,
                                                         win_vm, lin_vm)

        old_manager_state = get_manager_state(old_mgr, TENANTS, logger)

        prepare_credentials_tests(old_mgr, logger)

        create_copy_and_restore_snapshot(
            old_mgr, new_manager, SNAPSHOT_ID, local_snapshot_path,
            logger, wait_for_post_restore_commands=False)

        verify_services_status(new_manager, logger)
        check_credentials(new_manager, logger)

        # Use the new manager for the test deployments
        for example in example_mappings.values():
            example.manager = new_manager

        # We need to use the new manager when checking for files for the
        # from-source plugin
        example_mappings[FROM_SOURCE_TENANT].example_host = new_manager

        # Because of the way the from-source central executor plugin works, we
        # need to re-run the file creation so that checks for them succeed.
        example_mappings[FROM_SOURCE_TENANT].execute(
            'execute_operation',
            parameters={
                'node_ids': 'file',
                'operation': 'cloudify.interfaces.lifecycle.create',
            },
        )

        # Make sure we still have the test files after the restore
        for example in example_mappings.values():
            example.check_files()

        new_manager_state = get_manager_state(new_manager, TENANTS, logger)
        assert new_manager_state == old_manager_state
        check_deployments(new_manager, old_manager_state, logger)

        upgrade_agents(new_manager, logger, test_config)

        # The old manager needed to exist until the agents were upgraded, but
        # we want it not to afterwards so we don't pass the test due to the
        # old manager handling things we thought the new one was.
        stop_manager(old_mgr, logger)

        # Make sure the agent upgrade and old manager removal didn't
        # damage the test files
        for example in example_mappings.values():
            example.check_files()

        # Make sure we can still run deployment updates
        apply_and_check_deployment_update(
            new_manager, example_mappings[LIN_TENANT], logger)

        # Make sure we can correctly remove all test files
        for tenant, example in example_mappings.items():
            logger.info('Checking example deployment %s', tenant)
            if example.installed:
                logger.info('Uninstalling deployment for %s', tenant)
                example.uninstall()

        if old_ver != last_old_version:
            logger.info('Cleaning new manager for next restore')
            new_manager.teardown()
            new_manager.bootstrap()


def prepare_old_manager_resources(manager, logger, ssh_key, test_config,
                                  win_vm, lin_vm):
    """Install resources on the old manager.
    These are the resources we will be restoring on the new manager.
    """
    create_tenants(manager, logger, tenants=TENANTS)

    example_mappings = {}

    # A deployment with a plugin installed from-source
    # Note: This needs to be a central executor plugin or the later check will
    # fail.
    example_mappings[FROM_SOURCE_TENANT] = get_example_deployment(
        manager, ssh_key, logger, FROM_SOURCE_TENANT, test_config,
        using_agent=False, upload_plugin=False,
    )
    # We'll use an older blueprint style for this to confirm they still work
    example_mappings[FROM_SOURCE_TENANT].blueprint_file = get_resource_path(
        'blueprints/compute/central_executor_4_3_3.yaml'
    )

    # A 'normal' windows deployment
    example_mappings[WIN_TENANT] = get_example_deployment(
        manager, ssh_key, logger, WIN_TENANT, test_config,
        win_vm, suffix='_win',
    )
    example_mappings[WIN_TENANT].use_windows(win_vm.username, win_vm.password)

    # A 'normal' linux deployment
    example_mappings[LIN_TENANT] = get_example_deployment(
        manager, ssh_key, logger, LIN_TENANT, test_config,
        lin_vm, suffix='_lin',
    )

    # A deployment that hasn't been installed
    example_mappings[NOINSTALL_TENANT] = get_example_deployment(
        manager, ssh_key, logger, NOINSTALL_TENANT, test_config, lin_vm,
    )

    if manager.image_type == '5.1.0':
        # We need to use the updated windows agent or it can't work
        agent_url = (
            'https://cloudify-release-eu.s3-eu-west-1.amazonaws.com/cloudify/'
            '5.1.0/ga-release/cloudify-windows-agent_5.1.0-ga.exe'
        )
        tmp_path = '/tmp/winagent.exe'
        agent_destination = (
            '/opt/manager/resources/packages/agents/'
            'cloudify-windows-agent.exe'
        )
        manager.run_command('curl -Lo {} {}'.format(tmp_path, agent_url))
        manager.run_command('sudo cp {} {}'.format(
            tmp_path, agent_destination))

    for tenant in INSTALL_TENANTS:
        skip_validation = tenant == FROM_SOURCE_TENANT
        example_mappings[tenant].upload_and_verify_install(
            skip_plugins_validation=skip_validation,
        )
    example_mappings[NOINSTALL_TENANT].upload_blueprint()
    example_mappings[NOINSTALL_TENANT].create_deployment()

    create_tenant_secrets(manager, TENANTS, logger)

    return example_mappings


def create_tenant_secrets(manager, tenants, logger):
    """
        Create some secrets to allow us to confirm whether secrets are
        successfully restored by snapshots.

        :param manager: The manager to create secrets on.
        :param tenants: A list of tenants to create secrets for.
        :param logger: A logger to provide useful output.
    """
    logger.info('Creating secrets...')
    for tenant in tenants:
        with set_client_tenant(manager.client, tenant):
            manager.client.secrets.create(
                key=tenant,
                value=tenant,
            )
    logger.info('Secrets created.')


def create_tenants(manager, logger, tenants=('tenant1', 'tenant2')):
    for tenant in tenants:
        if tenant == 'default_tenant':
            continue
        logger.info('Creating tenant {tenant}'.format(tenant=tenant))
        manager.client.tenants.create(tenant)
        logger.info('Tenant {tenant} created.'.format(tenant=tenant))
    return tenants
