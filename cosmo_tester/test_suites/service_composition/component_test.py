from cosmo_tester.framework import util
from . import (_infra, _app, _check_custom_execute_operation,
               _verify_custom_execution_cancel_and_resume,
               _verify_deployments_and_nodes)


def test_component(image_based_manager, ssh_key, logger, test_config):
    tenant = 'test_component'
    infra = _infra(image_based_manager, ssh_key, logger, tenant, test_config)
    app = _app(image_based_manager, ssh_key, logger, tenant, test_config,
               blueprint_name='component')

    logger.info('Uploading infrastructure blueprint.')
    infra.upload_blueprint()
    logger.info('Deploying application blueprint, which deploys the '
                'infrastructure as component.')
    app.upload_and_verify_install()

    with util.set_client_tenant(app.manager.client, tenant):
        _verify_deployments_and_nodes(app, 2)
        _check_custom_execute_operation(app, logger)
        _verify_custom_execution_cancel_and_resume(app, logger)

        # verify that uninstall of app removes the infra + its deployment
        logger.info('Testing component uninstall.')
        app.uninstall()
        assert len(app.manager.client.deployments.list()) == 1


def test_nested_components(image_based_manager, ssh_key, logger, test_config):
    tenant = 'test_nested_components'
    nesting_app = _prepare_nested_components(image_based_manager, ssh_key,
                                             logger, test_config, tenant)
    nesting_app.upload_and_verify_install()
    with util.set_client_tenant(nesting_app.manager.client, tenant):
        _verify_deployments_and_nodes(nesting_app, 3)


def test_nested_components_cancel_install(
        image_based_manager, ssh_key, logger, test_config):
    tenant = 'test_nested_components_cancel_install'
    nesting_app = _prepare_nested_components(image_based_manager, ssh_key,
                                             logger, test_config, tenant)
    logger.info('Deploying parent application blueprint, which deploys the '
                'child app. as component, which in turn deploys the infra.')
    nesting_app.upload_blueprint()
    nesting_app.create_deployment()

    with util.set_client_tenant(nesting_app.manager.client, tenant):
        logger.info('Installing parent application deployment.')
        install = nesting_app.manager.client.executions.start(
            'nesting_app', 'install')
        infra_deployment = util.get_deployment_by_blueprint(nesting_app,
                                                            'infra')
        logger.info('Cancelling infrastructure installation.')
        util.cancel_install(nesting_app, infra_deployment.id)
        # verify that the cancellation actually failed the top parent
        util.wait_for_execution_status(nesting_app, install.id, 'failed')


def _prepare_nested_components(image_based_manager, ssh_key, logger,
                               test_config, tenant):
    infra = _infra(image_based_manager, ssh_key, logger, tenant, test_config)
    app = _app(image_based_manager, ssh_key, logger, tenant, test_config,
               blueprint_name='component')
    nesting_app = _app(image_based_manager, ssh_key, logger, tenant,
                       test_config, blueprint_name='nesting_component',
                       app_name='nesting_app')

    logger.info('Uploading infrastructure blueprint.')
    infra.upload_blueprint()
    logger.info('Uploading child application blueprint, which has the '
                'infrastructure as component.')
    app.upload_blueprint()
    return nesting_app
