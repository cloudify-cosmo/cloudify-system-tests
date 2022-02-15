from cosmo_tester.framework import util


def test_proxy(bootstrap_test_manager, logger, tmpdir, test_config):
    """Start a manager with proxy settings, and check that it uses the proxy.

    The operation is going to attempt to reach out to the internet, and
    it's going to assert that it fails with a proxy error, because there's
    no proxy set up. We only need to check that cloudify correctly attempts
    to use the proxy. We don't need to test the proxy itself.
    """
    manager = bootstrap_test_manager
    proxy_env = {
        'HTTP_PROXY': f'http://{manager.private_ip_address}',
        'HTTPS_PROXY': f'https://{manager.private_ip_address}',
        'NO_PROXY': f'{manager.private_ip_address},127.0.0.1,localhost',
    }
    manager.install_config.setdefault('stage', {}).update(
        extra_env=proxy_env)
    manager.install_config.setdefault('mgmtworker', {}).update(
        extra_env=proxy_env)
    manager.bootstrap(include_sanity=True)
    manager.client.blueprints.upload(
        util.get_resource_path(
            'blueprints/proxy/proxy_blueprint.yaml'
        ),
        'proxy_blueprint'
    )
    manager.client.deployments.create('proxy_blueprint', 'proxy_deployment')
    execution = manager.client.executions.create(
        'proxy_deployment',
        'execute_operation',
        parameters={'operation': 'run.via_proxy'}
    )
    util.wait_for_execution(manager.client, execution, logger)
