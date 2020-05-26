import os

from cloudify_cli.utils import (
    ExecutionFailed,
    get_deployment_environment_execution,
    wait_for_execution,
)
from cloudify_cli.constants import CREATE_DEPLOYMENT


NODES_BLUEPRINT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(
            __file__), '..', '..', 'resources/blueprints/scale/nodes.yaml'))
GROUPS_BLUEPRINT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(
            __file__), '..', '..', 'resources/blueprints/scale/groups.yaml'))
SCALING_TEST_BLUEPRINTS = {
    'nodes': NODES_BLUEPRINT_PATH,
    'groups': GROUPS_BLUEPRINT_PATH,
}


def _deploy_test_deployments(dep_type, manager, logger, entity_id=None):
    if entity_id is None:
        entity_id = dep_type
    logger.info('Deploying {dep} scaling blueprint'.format(dep=entity_id))
    blueprint_path = SCALING_TEST_BLUEPRINTS[dep_type]
    logger.info('Uploading blueprint for {dep}'.format(dep=entity_id))
    manager.client.blueprints.upload(
        path=blueprint_path,
        entity_id=entity_id,
    )

    logger.info('Creating deployment for {dep}'.format(dep=entity_id))
    manager.client.deployments.create(
        blueprint_id=entity_id,
        deployment_id=entity_id,
    )

    logger.info('Waiting for deployment env creation for '
                '{dep}'.format(dep=entity_id))
    creation_execution = get_deployment_environment_execution(
        manager.client, entity_id, CREATE_DEPLOYMENT)
    wait_for_execution(
        manager,
        creation_execution,
        logger,
    )

    logger.info('Running install for {dep}'.format(dep=entity_id))
    execution = manager.client.executions.start(
        entity_id,
        'install',
    )
    wait_for_execution(
        manager,
        execution,
        logger,
    )


def _get_deployed_instances(deployment, manager, logger):
    logger.info(
        'Getting list of deployed instances for {dep} blueprint'.format(
            dep=deployment,
        )
    )
    return [
        inst['id'] for inst in
        manager.client.node_instances.list(deployment_id=deployment)
    ]


def _test_error_message(manager,
                        logger,
                        expected_in_error,
                        parameters,
                        test_name,
                        deployment,
                        no_instance_list=False):
    logger.info('Testing: {test_name}'.format(test_name=test_name))
    execution = manager.client.executions.start(
        deployment,
        'scale',
        parameters=parameters,
    )

    try:
        wait_for_execution(manager, execution, logger)
        return (
            'Execution unexpected succeeded for {test_name}'.format(
                test_name=test_name,
            )
        )
    except ExecutionFailed:
        exec_result = manager.client.executions.get(execution['id'])
        error = exec_result['error'].lower()
        if all([component in error for component in expected_in_error]):
            if no_instance_list:
                return
            instances = _get_deployed_instances(deployment, manager, logger)
            if all([instance in error for instance in instances]):
                return
            else:
                return (
                    'Error message did not contain list of instances for '
                    '{test_name}. Instances were: {instances}. Error was: '
                    '{error}'.format(
                        test_name=test_name,
                        instances=', '.join(instances),
                        error=error,
                    )
                )
        else:
            return (
                'Error message did not contain expected components for test: '
                '{test_name}. Expected to find: {components}. Error was: '
                '{error}'.format(
                    test_name=test_name,
                    components=', '.join(expected_in_error),
                    error=error,
                )
            )


def test_targeted_scale_error_messages(image_based_manager, logger):
    _deploy_test_deployments('nodes', image_based_manager, logger)
    _deploy_test_deployments('groups', image_based_manager, logger)

    nodes_instances = _get_deployed_instances('nodes', image_based_manager,
                                              logger)
    groups_instances = _get_deployed_instances('groups', image_based_manager,
                                               logger)

    base_call = {
        'manager': image_based_manager,
        'logger': logger,
    }

    error_tests = [
        {
            'deployment': 'nodes',
            'expected_in_error': [
                'cannot be',
                'scaling up',
            ],
            'parameters': {
                'scalable_entity_name': 'fakevm',
                'delta': '+1',
                'include_instances': nodes_instances[0],
            },
            'test_name': 'Scale down with positive delta',
            'no_instance_list': True,
        },
        {
            'deployment': 'nodes',
            'expected_in_error': [
                'scale_compute is true',
            ],
            'parameters': {
                'scalable_entity_name': 'fakevm',
                'delta': '-1',
                'include_instances': nodes_instances[1],
                'scale_compute': True,
            },
            'test_name': 'Scale compute set to true',
        },
        {
            'deployment': 'nodes',
            'expected_in_error': [
                'included',
                'not exist',
            ],
            'parameters': {
                'scalable_entity_name': 'fakevm',
                'delta': '-1',
                'include_instances': groups_instances[0],
            },
            'test_name': 'Include non-existent instance',
        },
        {
            'deployment': 'nodes',
            'expected_in_error': [
                'excluded',
                'not exist',
            ],
            'parameters': {
                'scalable_entity_name': 'fakevm',
                'delta': '-1',
                'exclude_instances': groups_instances[1],
            },
            'test_name': 'Exclude non-existent instance',
        },
        {
            'deployment': 'nodes',
            'expected_in_error': [
                'both',
                'excluded and included',
            ],
            'parameters': {
                'scalable_entity_name': 'fakevm',
                'delta': '-1',
                'include_instances': nodes_instances[2],
                'exclude_instances': nodes_instances[2],
            },
            'test_name': 'Include and exclude same instance',
        },
        {
            'deployment': 'nodes',
            'expected_in_error': [
                'target',
                'less',
                'excluded',
            ],
            'parameters': {
                'scalable_entity_name': 'fakevm',
                'delta': '-1',
                'exclude_instances': nodes_instances,
            },
            'test_name': 'Exclude too many instances',
        },
        {
            'deployment': 'groups',
            'expected_in_error': [
                'too many',
                'groups',
                'excluded',
            ],
            'parameters': {
                'scalable_entity_name': 'vmgroup',
                'delta': '-1',
                # Because the groups are in groups of two instances, excluding
                # all but one instance should exclude all groups
                'exclude_instances': groups_instances[0:-1],
            },
            'test_name': 'Exclude too many groups',
        },
    ]

    issues = []
    for test in error_tests:
        test.update(base_call)
        failure = _test_error_message(**test)
        if failure:
            issues.append(failure)

    for issue in issues:
        logger.error(issue)
    assert not issues


def test_scale_down_target_node_instance(image_based_manager, logger):
    entity_id = 'testnodesinclude'
    _deploy_test_deployments('nodes', image_based_manager, logger,
                             entity_id=entity_id)
    nodes_instances = _get_deployed_instances(entity_id, image_based_manager,
                                              logger)

    delta = 3
    targets = nodes_instances[:delta]
    expected = nodes_instances[delta:]
    execution = image_based_manager.client.executions.start(
        entity_id,
        'scale',
        parameters={
            'scalable_entity_name': 'fakevm',
            'delta': '-{}'.format(delta),
            'include_instances': targets,
        },
    )
    wait_for_execution(image_based_manager, execution, logger)

    after_nodes_instances = _get_deployed_instances(entity_id,
                                                    image_based_manager,
                                                    logger)
    assert set(expected) == set(after_nodes_instances)


def test_do_not_scale_down_excluded_node_instance(image_based_manager,
                                                  logger):
    entity_id = 'testnodesexclude'
    _deploy_test_deployments('nodes', image_based_manager, logger,
                             entity_id=entity_id)
    nodes_instances = _get_deployed_instances(entity_id, image_based_manager,
                                              logger)

    execution = image_based_manager.client.executions.start(
        entity_id,
        'scale',
        parameters={
            'scalable_entity_name': 'fakevm',
            'delta': '-49',
            'exclude_instances': nodes_instances[-1],
        },
    )
    wait_for_execution(image_based_manager, execution, logger)

    after_nodes_instances = _get_deployed_instances(entity_id,
                                                    image_based_manager,
                                                    logger)

    assert [nodes_instances[-1]] == after_nodes_instances


def test_scale_down_target_node_instance_with_exclusions(image_based_manager,
                                                         logger):
    entity_id = 'testnodesincludeandexclude'
    _deploy_test_deployments('nodes', image_based_manager, logger,
                             entity_id=entity_id)
    nodes_instances = _get_deployed_instances(entity_id, image_based_manager,
                                              logger)

    included = nodes_instances[0:24]
    excluded = nodes_instances[24:48]
    optional = nodes_instances[48:]
    execution = image_based_manager.client.executions.start(
        entity_id,
        'scale',
        parameters={
            'scalable_entity_name': 'fakevm',
            'delta': '-25',
            'include_instances': included,
            'exclude_instances': excluded,
        },
    )
    wait_for_execution(image_based_manager, execution, logger)

    after_nodes_instances = _get_deployed_instances(entity_id,
                                                    image_based_manager,
                                                    logger)

    logger.info('Confirming correct number of instances remaining')
    assert len(after_nodes_instances) == 25
    logger.info('Checking all excluded instances are remaining')
    logger.info('Remaining instances: {inst}'.format(
        inst=after_nodes_instances,
    ))
    logger.info('Excluded: {excl}'.format(excl=after_nodes_instances))
    assert all([inst in after_nodes_instances for inst in excluded])
    logger.info('Checking only one of the following remains: {inst}'.format(
        inst=optional,
    ))
    assert (
        (optional[0] in after_nodes_instances) ^
        (optional[1] in after_nodes_instances)
    )


def test_scale_down_target_group_member(image_based_manager, logger):
    entity_id = 'testgroupinclude'
    _deploy_test_deployments('groups', image_based_manager, logger,
                             entity_id=entity_id)
    groups_instances = _get_deployed_instances(entity_id, image_based_manager,
                                               logger)

    execution = image_based_manager.client.executions.start(
        entity_id,
        'scale',
        parameters={
            'scalable_entity_name': 'vmgroup',
            'delta': '-3',
            'include_instances': groups_instances[0],
        },
    )
    wait_for_execution(image_based_manager, execution, logger)

    after_groups_instances = _get_deployed_instances(entity_id,
                                                     image_based_manager,
                                                     logger)

    assert len(after_groups_instances) == 34
    assert groups_instances[0] not in after_groups_instances


def test_scale_down_do_not_target_excluded_group_member(image_based_manager,
                                                        logger):
    entity_id = 'testgroupexclude'
    _deploy_test_deployments('groups', image_based_manager, logger,
                             entity_id=entity_id)
    groups_instances = _get_deployed_instances(entity_id, image_based_manager,
                                               logger)

    execution = image_based_manager.client.executions.start(
        entity_id,
        'scale',
        parameters={
            'scalable_entity_name': 'vmgroup',
            'delta': '-19',
            'exclude_instances': groups_instances[0],
        },
    )
    wait_for_execution(image_based_manager, execution, logger)

    after_groups_instances = _get_deployed_instances(entity_id,
                                                     image_based_manager,
                                                     logger)

    assert len(after_groups_instances) == 2
    assert groups_instances[0] in after_groups_instances
