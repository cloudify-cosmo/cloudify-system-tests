import pytest

from cosmo_tester.framework import util
from cosmo_tester.framework.test_hosts import Hosts
from . import (_infra, _app, _check_custom_execute_operation,
               _verify_deployments_and_nodes)
from cloudify_rest_client.exceptions import CloudifyClientError


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
    local_mgr, external_mgr = managers

    ext_username = 'dave'
    ext_password = 'swordfish'
    external_mgr.client.users.create(ext_username, ext_password, 'sys_admin')

    # copy the app manager's CA cert to the infra manager
    ext_mgr_cert_path = '/etc/cloudify/ssl/ext_mgr_internal_ca_cert.pem'
    local_mgr.put_remote_file(ext_mgr_cert_path, external_mgr.api_ca_path)

    infra = _infra(external_mgr, ssh_key, logger, tenant, test_config)
    app = _app(local_mgr, ssh_key, logger, tenant, test_config,
               blueprint_name='shared_resource',
               client_ip=external_mgr.private_ip_address,
               client_username=ext_username,
               client_password=ext_password,
               ca_cert_path=ext_mgr_cert_path)

    logger.info('Deploying the shared resource on an external manager.')
    infra.upload_blueprint()
    infra.create_deployment()
    logger.info('Deploying an application which uses the resource, '
                'on the local manager.')
    app.upload_and_verify_install()

    logger.info('Verifying inter-deployment dependency on both managers')
    with util.set_client_tenant(app.manager.client, tenant):
        local_idd = app.manager.client.inter_deployment_dependencies.list()[0]
        assert local_idd['source_deployment_id'] == 'app'
        assert local_idd['dependency_creator'].startswith('sharedresource.')
        assert local_idd['external_target']['deployment'] == 'infra'
        assert local_idd['external_target']['client_config']['host'] == \
            external_mgr.private_ip_address

    with util.set_client_tenant(infra.manager.client, tenant):
        external_idd = \
            infra.manager.client.inter_deployment_dependencies.list()[0]
        assert external_idd['target_deployment_id'] == 'infra'
        assert external_idd['dependency_creator'].startswith('sharedresource.')
        assert external_idd['external_source']['deployment'] == 'app'
        assert external_idd['external_source']['host'] == \
            [local_mgr.private_ip_address]

    logger.info('Verifying that uninstalling the resource is blocked because '
                'there is a dependent deployment')
    with pytest.raises(CloudifyClientError) as e:
        infra.uninstall()
    error_msg = \
        "Can't execute workflow `uninstall` on deployment infra - the " \
        "following existing installations depend on it:\n  [1] Deployment " \
        "`app on ['{0}']` uses a shared resource from the current " \
        "deployment".format(local_mgr.private_ip_address)
    assert error_msg in str(e.value)
