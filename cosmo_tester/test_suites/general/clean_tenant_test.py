from retrying import retry

from cosmo_tester.framework.examples import get_example_deployment


def test_clean_tenant(image_based_manager, ssh_key, tmpdir, logger,
                      test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'cleanthistenant',
        test_config)
    example.upload_and_verify_install()
    example.uninstall()

    _purge_tenant('cleanthistenant', image_based_manager, logger)

    remaining_paths = image_based_manager.run_command(
        'find /opt -name cleanthistenant', use_sudo=True,
    ).stdout.strip().splitlines()

    for path in remaining_paths:
        # Sidestep pytest truncation fun
        logger.warning('Found unexpected remaining path: %s', path)
    assert not remaining_paths


@retry(stop_max_attempt_number=3, wait_fixed=3000)
def _purge_tenant(tenant_name, manager, logger):
    tenant_client = manager.get_rest_client(tenant=tenant_name)

    logger.info('Deleting any deployments for %s...', tenant_name)
    _clean_resource(tenant_client.deployments, logger)
    logger.info('Deleting any blueprints for %s...', tenant_name)
    _clean_resource(tenant_client.blueprints, logger)
    logger.info('Deleting any plugins for %s...', tenant_name)
    _clean_resource(tenant_client.plugins, logger)

    logger.info('Deleting tenant %s', tenant_name)
    manager.client.tenants.delete(tenant_name)
    logger.info('Tenant %s deleted', tenant_name)


@retry(stop_max_attempt_number=3, wait_fixed=3000)
def _clean_resource(resource_client, logger):
    for resource in resource_client.list():
        logger.info('Deleting %s', resource['id'])
        resource_client.delete(resource['id'])
