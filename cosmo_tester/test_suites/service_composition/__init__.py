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
    example.inputs = {}
    return example


def _app(image_based_manager, ssh_key, logger, tenant, test_config,
         blueprint_name, app_name='app'):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, tenant, test_config,
        upload_plugin=False)

    example.blueprint_file = util.get_resource_path(
        'blueprints/service_composition/{0}.yaml'.format(blueprint_name)
    )
    example.blueprint_id = app_name
    example.deployment_id = app_name
    example.inputs['agent_user'] = image_based_manager.username
    example.create_secret = False   # don't try to create it twice
    return example


def _check_custom_execute_operation(app, logger):
    logger.info('Testing custom execute operation.')
    util.run_blocking_execution(
        app.manager.client, 'app', 'execute_operation', logger,
        params={'operation': 'maintenance.poll', 'node_ids': 'app'})
    assert app.manager.client.executions.list(
        workflow_id='execute_operation')[0].status == 'terminated'


def _verify_custom_execution_cancel_and_resume(app, logger):
    # plant runtime property which conditions the execution to fail
    instances = app.manager.client.node_instances.list(deployment_id='app',
                                                       node_id='app')
    app.manager.client.node_instances.update(
        instances[0].id,
        runtime_properties={'fail_commit': True},
        version=instances[0].version + 1
    )
    rollout = app.manager.client.executions.start('app', 'rollout')

    logger.info('Testing execution cancel.')
    app.manager.client.executions.cancel(rollout.id)
    util.wait_for_execution_status(app, rollout.id, 'cancelled')

    app.manager.client.node_instances.update(
        instances[0].id,
        runtime_properties={'fail_commit': False},
        version=instances[0].version + 1
    )
    logger.info('Testing execution resume.')
    app.manager.client.executions.resume(rollout.id)
    util.wait_for_execution_status(app, rollout.id, 'terminated')


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
