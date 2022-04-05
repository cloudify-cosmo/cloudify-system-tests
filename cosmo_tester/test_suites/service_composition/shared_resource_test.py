import pytest

from cosmo_tester.framework import util
from cosmo_tester.framework.test_hosts import Hosts
from . import (_infra, _app, _check_custom_execute_operation,
               _verify_deployments_and_nodes)
from cloudify_rest_client.exceptions import CloudifyClientError


# The on_demand and non-on-demand tests are in the same tests as each other
# to cut down on test time.
# It is expected that multi-tenancy will make this safe to do.
def test_shared_resource(image_based_manager, ssh_key, logger, test_config):
    tenant = 'test_shared_resource'
    app = _app(image_based_manager, ssh_key, logger, tenant, test_config,
               blueprint_name='shared_resource',
               client_password=image_based_manager.mgr_password)

    _prepare_infra(image_based_manager, ssh_key, logger, tenant, test_config)
    app = _prepare_and_deploy_app(
        image_based_manager, ssh_key, logger, tenant, test_config,
        blueprint_name='shared_resource',
        client_password=image_based_manager.mgr_password)

    with util.set_client_tenant(app.manager.client, tenant):
        _verify_deployments_and_nodes(app, 2)
        _check_custom_execute_operation(app, logger)

    od_tenant = 'test_on_demand_shared_resource'
    _prepare_infra(image_based_manager, ssh_key, logger, od_tenant,
                   test_config, on_demand=True)
    od_app = _prepare_and_deploy_app(
        image_based_manager, ssh_key, logger, od_tenant,
        test_config, blueprint_name='shared_resource',
        client_password=image_based_manager.mgr_password)

    with util.set_client_tenant(od_app.manager.client, od_tenant):
        _verify_deployments_and_nodes(od_app, 2)
        _check_custom_execute_operation(od_app, logger)


@pytest.fixture(scope='function')
def managers(request, ssh_key, module_tmpdir, test_config, logger):
    hosts = Hosts(ssh_key, module_tmpdir, test_config, logger, request, 2)
    passed = True
    try:
        hosts.create()
        yield hosts.instances
    except Exception:
        passed = False
        raise
    finally:
        hosts.destroy(passed=passed)


def test_external_shared_resource_idd(managers, ssh_key, logger, test_config,
                                      tmpdir):
    tenant = 'test_external_shared_resource_idd'
    target_deployment_id = 'infra'
    source_deployment_id = 'app'

    local_mgr, external_mgr = managers

    # copy the app manager's CA cert to the infra manager
    ext_mgr_cert_path = '/etc/cloudify/ssl/ext_mgr_internal_ca_cert.pem'
    local_mgr.put_remote_file(ext_mgr_cert_path, external_mgr.api_ca_path)

    infra = _prepare_infra(external_mgr, ssh_key, logger, tenant, test_config)
    app = _prepare_and_deploy_app(
        local_mgr, ssh_key, logger, tenant, test_config,
        blueprint_name='shared_resource',
        client_ip=external_mgr.private_ip_address,
        client_password=external_mgr.mgr_password,
        ca_cert_path=ext_mgr_cert_path)

    _check_external_idd(app, infra, tenant, local_mgr, external_mgr,
                        source_deployment_id, target_deployment_id, logger)

    od_tenant = 'test_external_shared_resource_idd_on_demand'
    od_infra = _prepare_infra(external_mgr, ssh_key, logger, od_tenant,
                              test_config)
    od_app = _prepare_and_deploy_app(
        local_mgr, ssh_key, logger, od_tenant, test_config,
        blueprint_name='shared_resource',
        client_ip=external_mgr.private_ip_address,
        client_password=external_mgr.mgr_password,
        ca_cert_path=ext_mgr_cert_path)

    _check_external_idd(od_app, od_infra, od_tenant, local_mgr, external_mgr,
                        source_deployment_id, target_deployment_id, logger)


def _prepare_infra(manager, ssh_key, logger, tenant, test_config,
                   on_demand=False):
    infra = _infra(manager, ssh_key, logger, tenant, test_config)

    logger.info('Deploying the shared resource on a %s.', manager.ip_address)
    infra.upload_blueprint()
    infra.create_deployment()

    if on_demand:
        logger.info('Making shared resource be on-demand')
        with util.set_client_tenant(manager.client, tenant):
            manager.client.deployments.update_labels(
                'infra', [{'csys-obj-type': 'on-demand-resource'}])
    else:
        infra.install()

    return infra


def _prepare_and_deploy_app(manager, ssh_key, logger, tenant, test_config,
                            blueprint_name, client_ip=None,
                            client_username='admin', client_password=None,
                            ca_cert_path=None):
    app = _app(manager, ssh_key, logger, tenant, test_config,
               blueprint_name=blueprint_name, client_ip=client_ip,
               client_username=client_username,
               client_password=client_password,
               ca_cert_path=ca_cert_path)
    logger.info('Deploying application on %s which uses shared resource.',
                manager.ip_address)
    app.upload_and_verify_install()

    return app


def _check_external_idd(app, infra, tenant, local_mgr, external_mgr,
                        source_deployment_id, target_deployment_id,
                        logger):
    logger.info('Verifying inter-deployment dependency on both managers')
    with util.set_client_tenant(app.manager.client, tenant):
        local_idd = app.manager.client.inter_deployment_dependencies.list()[0]
        assert local_idd['source_deployment_id'] == source_deployment_id
        assert local_idd['dependency_creator'].startswith('sharedresource.')
        assert local_idd['external_target']['deployment'] == \
            target_deployment_id
        assert local_idd['external_target']['client_config']['host'] == \
            external_mgr.private_ip_address

    with util.set_client_tenant(infra.manager.client, tenant):
        external_idd = \
            infra.manager.client.inter_deployment_dependencies.list()[0]
        assert external_idd['target_deployment_id'] == target_deployment_id
        assert external_idd['dependency_creator'].startswith('sharedresource.')
        assert external_idd['external_source']['deployment'] == \
            source_deployment_id
        assert external_idd['external_source']['host'] == \
            [local_mgr.ip_address]

    logger.info('Verifying that uninstalling the resource is blocked because '
                'there is a dependent deployment')
    with pytest.raises(CloudifyClientError) as e:
        infra.uninstall()

    expected_error_msg_components = [
        "Can't execute",
        "uninstall",  # The workflow
        target_deployment_id,
        source_deployment_id,
        "existing",
        "depend",
        "EXTERNAL",
        tenant,
        local_mgr.ip_address,
    ]
    for component in expected_error_msg_components:
        assert component in str(e.value)
