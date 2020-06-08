from cosmo_tester.framework import util
from . import (_infra, _app, _check_custom_execute_operation,
               _verify_custom_execution_cancel_and_resume,
               _verify_deployments_and_nodes)


def test_shared_resource(image_based_manager, ssh_key, logger, test_config):
    tenant = 'test_shared_resource'
    infra = _infra(image_based_manager, ssh_key, logger, tenant, test_config)
    app = _app(image_based_manager, ssh_key, logger, tenant, test_config,
               blueprint_name='shared_resource')

    logger.info('Deploying the blueprint which contains a shared resource.')
    infra.upload_blueprint()
    infra.create_deployment()
    logger.info('Deploying application blueprint, which uses the resource.')
    app.upload_and_verify_install()

    with util.set_client_tenant(app.manager.client, tenant):
        _verify_deployments_and_nodes(app, 2)
        _check_custom_execute_operation(app, logger)
        _verify_custom_execution_cancel_and_resume(app, logger)
