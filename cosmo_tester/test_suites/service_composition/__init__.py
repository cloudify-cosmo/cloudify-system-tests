from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment


def _infra(image_based_manager, ssh_key, logger, tenant, test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, tenant, test_config,
        upload_plugin=False)

    example.blueprint_file = util.get_resource_path(
        'blueprints/service_composition/fake_vm.yaml'
    )
    example.blueprint_id = 'infra'
    example.deployment_id = 'infra'
    example.inputs = {'agent_user': image_based_manager.username}
    return example


def _app(image_based_manager, ssh_key, logger, tenant, test_config,
         blueprint_name, app_name='app', client_ip=None,
         client_username='admin', client_password='admin', ca_cert_path=None):
    if not client_ip:
        client_ip = image_based_manager.private_ip_address

    example = get_example_deployment(
        image_based_manager, ssh_key, logger, tenant, test_config,
        upload_plugin=False)

    example.blueprint_file = util.get_resource_path(
        'blueprints/service_composition/{0}.yaml'.format(blueprint_name)
    )
    example.blueprint_id = app_name
    example.deployment_id = app_name
    example.inputs['agent_user'] = image_based_manager.username
    example.inputs['client_ip'] = client_ip
    example.inputs['client_tenant'] = tenant
    example.inputs['client_username'] = client_username
    example.inputs['client_password'] = client_password
    if ca_cert_path:
        example.inputs['ca_cert_path'] = ca_cert_path
    example.create_secret = False   # don't try to create it twice
    return example


def _check_custom_execute_operation(app, logger):
    logger.info('Testing custom execute operation.')
    util.run_blocking_execution(
        app.manager.client, 'app', 'execute_operation', logger,
        params={'operation': 'maintenance.poll', 'node_ids': 'app'})
    assert app.manager.client.executions.list(
        workflow_id='execute_operation')[0].status == 'terminated'


def _verify_deployments_and_nodes(app, number_of_deployments):
    # verify all deployments exist
    assert len(app.manager.client.deployments.list()) == number_of_deployments
    # assert all compute instances are alive
    nodes = app.manager.client.nodes.list()
    assert len(set(node.deployment_id for node in nodes)) == \
        number_of_deployments
    for node in nodes:
        if node.type == 'cloudify.nodes.Compute':
            assert node.number_of_instances == 1
