########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import pytest
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    check_credentials,
    check_deployments,
    verify_services_status,
    change_salt_on_new_manager,
    check_from_source_plugin,
    check_plugins,
    confirm_manager_empty,
    create_snapshot,
    stop_manager,
    download_snapshot,
    get_deployments_list,
    get_plugins_list,
    get_secrets_list,
    prepare_credentials_tests,
    restore_snapshot,
    set_client_tenant,
    SNAPSHOT_ID,
    update_credentials,
    upgrade_agents,
    upload_snapshot,
    wait_for_restore,
)


def test_restore_snapshot_and_agents_upgrade_multitenant(
        hosts, logger, tmpdir, ssh_key, test_config):
    if not test_config['premium']:
        pytest.skip('Multi tenant snapshots are not valid for community.')
    local_snapshot_path = str(tmpdir / 'snapshot.zip')

    from_source_tenant = 'from_source'
    standard_deployment_tenant = 'default_tenant'
    noinstall_tenant = 'noinstall'

    install_tenants = [from_source_tenant, standard_deployment_tenant]
    tenants = [from_source_tenant, standard_deployment_tenant,
               noinstall_tenant]

    old_manager, new_manager, vm = hosts.instances

    confirm_manager_empty(new_manager)

    create_tenants(old_manager, logger, tenants=tenants)

    example_mappings = {}

    # A deployment with a plugin installed from-source
    # Note: This needs to be a central executor plugin or the later check will
    # fail.
    example_mappings[from_source_tenant] = get_example_deployment(
        old_manager, ssh_key, logger, from_source_tenant, test_config,
        using_agent=False, upload_plugin=False,
    )

    # A 'normal' deployment
    example_mappings[standard_deployment_tenant] = get_example_deployment(
        old_manager, ssh_key, logger, standard_deployment_tenant, test_config,
        vm,
    )

    # A deployment that hasn't been installed
    example_mappings[noinstall_tenant] = get_example_deployment(
        old_manager, ssh_key, logger, noinstall_tenant, test_config, vm,
    )

    for tenant in install_tenants:
        skip_validation = tenant == from_source_tenant
        example_mappings[tenant].upload_and_verify_install(
            skip_plugins_validation=skip_validation,
        )
    example_mappings[noinstall_tenant].upload_blueprint()
    example_mappings[noinstall_tenant].create_deployment()

    create_tenant_secrets(old_manager, tenants, logger)

    old_plugins = {
        tenant: get_plugins_list(old_manager, tenant)
        for tenant in tenants
    }
    old_secrets = {
        tenant: get_secrets_list(old_manager, tenant)
        for tenant in tenants
    }
    old_deployments = {
        tenant: get_deployments_list(old_manager, tenant)
        for tenant in tenants
    }

    change_salt_on_new_manager(new_manager, logger)
    prepare_credentials_tests(old_manager, logger)

    create_snapshot(old_manager, SNAPSHOT_ID, logger)
    download_snapshot(old_manager, local_snapshot_path, SNAPSHOT_ID, logger)
    upload_snapshot(new_manager, local_snapshot_path, SNAPSHOT_ID, logger)

    restore_snapshot(new_manager, SNAPSHOT_ID, logger,
                     wait_for_post_restore_commands=False)

    wait_for_restore(new_manager, logger)

    update_credentials(new_manager, new_manager)

    verify_services_status(new_manager, logger)

    check_credentials(new_manager, logger)

    # Use the new manager for the test deployments
    for example in example_mappings.values():
        example.manager = new_manager

    # We need to use the new manager when checking for files for the
    # from-source plugin
    example_mappings[from_source_tenant].example_host = new_manager

    # Because of the way the from-source central executor plugin works, we
    # need to re-run the file creation so that checks for them will succeed.
    example_mappings[from_source_tenant].execute(
        'execute_operation',
        parameters={
            'node_ids': 'file',
            'operation': 'cloudify.interfaces.lifecycle.create',
        },
    )

    # Make sure we still have the test files after the restore
    for example in example_mappings.values():
        example.check_files()

    # We don't check agent keys are converted to secrets because that is only
    # expected to happen for 3.x restores now.
    check_tenant_secrets(new_manager, tenants, old_secrets, logger)
    check_tenant_plugins(new_manager, old_plugins, tenants, logger)
    check_tenant_deployments(new_manager, old_deployments, tenants, logger)
    check_tenant_source_plugins(
        new_manager, 'test_plugin',
        example_mappings[from_source_tenant].deployment_id,
        [from_source_tenant], logger,
    )

    upgrade_agents(new_manager, logger, test_config)

    # The old manager needs to exist until the agents install is run
    stop_manager(old_manager, logger)

    # Make sure the agent upgrade and old manager removal didn't
    # damage the test files
    for example in example_mappings.values():
        example.check_files()

    # Make sure we can correctly remove all test files
    for example in example_mappings.values():
        if example.installed:
            example.uninstall()


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
        with set_client_tenant(manager, tenant):
            manager.client.secrets.create(
                key=tenant,
                value=tenant,
            )
        assert tenant in get_secrets_list(manager, tenant), (
            'Failed to create secret for {tenant}'.format(tenant=tenant)
        )
    logger.info('Secrets created.')


def check_tenant_secrets(manager, tenants, old_secrets, logger):
    """
        Check that secrets are correctly restored onto a new manager.
        This includes confirming that no new secrets are created except for
        those that are created as part of the SSH key -> secret migrations.

        :param manager: The manager to check for restored secrets.
        :param tenants: The tenants to check.
        :param old_secrets: A dict containing lists of secrets keyed by tenant
                            name.
        :param logger: A logger to provide useful output.
    """
    for tenant in tenants:
        logger.info('Checking secrets for {tenant}'.format(tenant=tenant))
        non_agentkey_secrets = [
            secret for secret in get_secrets_list(manager, tenant)
            if not secret.startswith('cfyagent_key__')
        ]
        non_agentkey_secrets.sort()
        logger.info('Found secrets for {tenant} on manager: {secrets}'.format(
            tenant=tenant,
            secrets=', '.join(non_agentkey_secrets),
        ))

        old_tenant_secrets = old_secrets[tenant]
        old_tenant_secrets.sort()

        assert non_agentkey_secrets == old_tenant_secrets, (
            'Secrets for {tenant} do not match old secrets!'.format(
                tenant=tenant,
            )
        )
        logger.info('Secrets for {tenant} are correct.'.format(tenant=tenant))


def check_tenant_plugins(manager, old_plugins, tenants, logger):
    logger.info('Checking uploaded plugins are correct for all tenants.')
    for tenant in tenants:
        check_plugins(manager, old_plugins[tenant], logger, tenant)
    logger.info('Uploaded plugins are correct for all tenants.')


def check_tenant_deployments(manager, old_deployments, tenants, logger):
    logger.info('Checking deployments are correct for all tenants.')
    for tenant in tenants:
        check_deployments(manager, old_deployments[tenant], logger,
                          tenant=tenant)
    logger.info('Deployments are correct for all tenants.')


def check_tenant_source_plugins(manager, plugin, deployment_id, tenants,
                                logger):
    logger.info(
        'Checking from-source plugin installs for tenants: {tenants}'.format(
            tenants=', '.join(tenants),
        )
    )
    for tenant in tenants:
        check_from_source_plugin(manager, plugin, deployment_id, logger,
                                 tenant)
    logger.info('Plugins installed from source were installed correctly.')


def create_tenants(manager, logger, tenants=('tenant1', 'tenant2')):
    for tenant in tenants:
        if tenant == 'default_tenant':
            continue
        logger.info('Creating tenant {tenant}'.format(tenant=tenant))
        manager.client.tenants.create(tenant)
        logger.info('Tenant {tenant} created.'.format(tenant=tenant))
    return tenants
