import json

import pytest

from . import _assert_summary_equal, DEPLOYMENTS_PER_SITE


DEPLOYMENTS_PER_BLUEPRINT = [
    {'blueprint_id': 'relations', 'deployments': 3},
    {'blueprint_id': 'small', 'deployments': 2},
    {'blueprint_id': 'multivm', 'deployments': 1}
]


def test_basic_summary_blueprints(prepared_manager):
    results = prepared_manager.client.summary.blueprints.get(
        _target_field='tenant_name', _all_tenants=True,).items

    expected = [
        {u'blueprints': 3, u'tenant_name': u'test1'},
        {u'blueprints': 3, u'tenant_name': u'test2'},
        {u'blueprints': 3, u'tenant_name': u'default_tenant'},
    ]

    _assert_summary_equal(results, expected)


@pytest.mark.parametrize('target_field, value', [
    ('blueprint_id', DEPLOYMENTS_PER_BLUEPRINT),
    ('site_name', DEPLOYMENTS_PER_SITE)
])
def test_basic_summary_deployments(prepared_manager, target_field, value):
    results = prepared_manager.client.summary.deployments.get(
        _target_field=target_field,).items

    _assert_summary_equal(results, value)


@pytest.mark.parametrize("target_field, value", [
    ("status", "terminated"),
    ("status_display", "completed")
])
def test_basic_summary_executions(prepared_manager, target_field, value):
    results = prepared_manager.client.summary.executions.get(
        _target_field=target_field,).items

    expected = [{u'executions': 15,
                 u'{0}'.format(target_field): u'{0}'.format(value)}]

    _assert_summary_equal(results, expected)


def test_basic_summary_nodes(prepared_manager):
    results = prepared_manager.client.summary.nodes.get(
        _target_field='deployment_id',).items

    expected = [
        {u'deployment_id': u'multivm0', u'nodes': 2},
        {u'deployment_id': u'relations0', u'nodes': 5},
        {u'deployment_id': u'relations1', u'nodes': 5},
        {u'deployment_id': u'relations2', u'nodes': 5},
        {u'deployment_id': u'small0', u'nodes': 1},
        {u'deployment_id': u'small1', u'nodes': 1}
    ]

    _assert_summary_equal(results, expected)


def test_basic_summary_node_instances(prepared_manager):
    # Note that this should use host_id to make sure at least one test
    # involves some entries that are NULL in the database, because if the
    # query is changed it could start counting all NULL entries as 1 again
    results = prepared_manager.client.summary.node_instances.get(
        _target_field='host_id',).items

    assert {u'host_id': None, u'node_instances': 6} in results

    results_counts = sorted([item['node_instances'] for item in results])
    expected_counts = [1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 6]

    assert expected_counts == results_counts, (
        'Results: {0}\n'
        'Expected host_id None to have 6 results.\n'
        'Expected counts: {1}\n'
        'Instance counts: {2}'.format(results,
                                      expected_counts,
                                      results_counts)
    )


def test_subfield_summary_blueprints(prepared_manager):
    results = prepared_manager.client.summary.blueprints.get(
        _target_field='tenant_name',
        _sub_field='visibility',
        _all_tenants=True,).items

    expected = [
        {
            u'tenant_name': u'default_tenant',
            u'blueprints': 3,
            u'by visibility': [
                {u'blueprints': 3, u'visibility': u'tenant'}
            ]
        },
        {
            u'tenant_name': u'test1',
            u'blueprints': 3,
            u'by visibility': [
                {u'blueprints': 3, u'visibility': u'tenant'}
            ]
        },
        {
            u'tenant_name': u'test2',
            u'blueprints': 3,
            u'by visibility': [
                {u'blueprints': 3, u'visibility': u'tenant'}
            ]
        }
    ]

    _assert_summary_equal(results, expected)


def test_subfield_summary_deployments(prepared_manager):
    results = prepared_manager.client.summary.deployments.get(
        _target_field='tenant_name',
        _sub_field='blueprint_id',
        _all_tenants=True,).items

    expected = [
        {
            u'by blueprint_id': [
                {u'blueprint_id': u'multivm', u'deployments': 1},
                {u'blueprint_id': u'relations', u'deployments': 3},
                {u'blueprint_id': u'small', u'deployments': 2}
            ],
            u'deployments': 6,
            u'tenant_name': u'default_tenant'
        },
        {
            u'by blueprint_id': [
                {u'blueprint_id': u'multivm', u'deployments': 2},
                {u'blueprint_id': u'relations', u'deployments': 1},
                {u'blueprint_id': u'small', u'deployments': 3}
            ],
            u'deployments': 6,
            u'tenant_name': u'test2'
        },
        {
            u'by blueprint_id': [
                {u'blueprint_id': u'multivm', u'deployments': 3},
                {u'blueprint_id': u'relations', u'deployments': 2},
                {u'blueprint_id': u'small', u'deployments': 1}
            ],
            u'deployments': 6,
            u'tenant_name': u'test1'
        }
    ]

    for result in results:
        original_lst = result['by blueprint_id']
        result[u'by blueprint_id'] = sorted(original_lst,
                                            key=lambda x: x['blueprint_id'])

    _assert_summary_equal(results, expected)


def test_subfield_summary_executions(prepared_manager):
    results = prepared_manager.client.summary.executions.get(
        _target_field='deployment_id',
        _sub_field='workflow_id',).items

    expected = [
        {
            u'by workflow_id': [
                {
                    u'executions': 3,
                    u'workflow_id': u'upload_blueprint'
                },
            ],
            u'deployment_id': None,
            u'executions': 3
        },
        {
            u'by workflow_id': [
                {
                    u'executions': 1,
                    u'workflow_id': u'create_deployment_environment'
                },
                {u'executions': 1, u'workflow_id': u'install'}
            ],
            u'deployment_id': u'multivm0',
            u'executions': 2
        },
        {
            u'by workflow_id': [
                {
                    u'executions': 1,
                    u'workflow_id': u'create_deployment_environment'
                },
                {u'executions': 1, u'workflow_id': u'install'}
            ],
            u'deployment_id': u'relations0',
            u'executions': 2
        },
        {
            u'by workflow_id': [
                {
                    u'executions': 1,
                    u'workflow_id': u'create_deployment_environment'
                },
                {u'executions': 1, u'workflow_id': u'install'}
            ],
            u'deployment_id': u'relations1',
            u'executions': 2
        },
        {
            u'by workflow_id': [
                {
                    u'executions': 1,
                    u'workflow_id': u'create_deployment_environment'
                },
                {u'executions': 1, u'workflow_id': u'install'}
            ],
            u'deployment_id': u'relations2',
            u'executions': 2
        },
        {
            u'by workflow_id': [
                {
                    u'executions': 1,
                    u'workflow_id': u'create_deployment_environment'
                },
                {u'executions': 1, u'workflow_id': u'install'}
            ],
            u'deployment_id': u'small0',
            u'executions': 2
        },
        {
            u'by workflow_id': [
                {
                    u'executions': 1,
                    u'workflow_id': u'create_deployment_environment'
                },
                {u'executions': 1, u'workflow_id': u'install'}
            ],
            u'deployment_id': u'small1',
            u'executions': 2
        }
    ]

    _assert_summary_equal(results, expected)


def test_subfield_summary_nodes(prepared_manager):
    results = prepared_manager.client.summary.nodes.get(
        _target_field='tenant_name',
        _sub_field='deployment_id',
        _all_tenants=True,).items

    expected = [
        {
            u'by deployment_id': [
                {u'deployment_id': u'multivm0', u'nodes': 2},
                {u'deployment_id': u'multivm1', u'nodes': 2},
                {u'deployment_id': u'multivm2', u'nodes': 2},
                {u'deployment_id': u'relations0', u'nodes': 5},
                {u'deployment_id': u'relations1', u'nodes': 5},
                {u'deployment_id': u'small0', u'nodes': 1}
            ],
            u'nodes': 17,
            u'tenant_name': u'test1'
        },
        {
            u'by deployment_id': [
                {u'deployment_id': u'multivm0', u'nodes': 2},
                {u'deployment_id': u'multivm1', u'nodes': 2},
                {u'deployment_id': u'relations0', u'nodes': 5},
                {u'deployment_id': u'small0', u'nodes': 1},
                {u'deployment_id': u'small1', u'nodes': 1},
                {u'deployment_id': u'small2', u'nodes': 1}
            ],
            u'nodes': 12,
            u'tenant_name': u'test2'
        },
        {
            u'by deployment_id': [
                {u'deployment_id': u'multivm0', u'nodes': 2},
                {u'deployment_id': u'relations0', u'nodes': 5},
                {u'deployment_id': u'relations1', u'nodes': 5},
                {u'deployment_id': u'relations2', u'nodes': 5},
                {u'deployment_id': u'small0', u'nodes': 1},
                {u'deployment_id': u'small1', u'nodes': 1}
            ],
            u'nodes': 19,
            u'tenant_name': u'default_tenant'
        }
    ]

    _assert_summary_equal(results, expected)


def test_subfield_summary_node_instances(prepared_manager):
    results = prepared_manager.client.summary.node_instances.get(
        _target_field='node_id', _sub_field='state').items

    expected = [
        {
            u'by state': [
                {u'node_instances': 3, u'state': u'started'}
            ],
            u'node_id': u'fakeappconfig1',
            u'node_instances': 3
        },
        {
            u'by state': [
                {u'node_instances': 3, u'state': u'started'}
            ],
            u'node_id': u'fakeplatformthing1',
            u'node_instances': 3},
        {
            u'by state': [
                {u'node_instances': 4, u'state': u'started'}
            ],
            u'node_id': u'fakevm2',
            u'node_instances': 4
        },
        {
            u'by state': [
                {u'node_instances': 6, u'state': u'started'}
            ],
            u'node_id': u'fakeapp1',
            u'node_instances': 6
        },
        {
            u'by state': [
                {u'node_instances': 9, u'state': u'started'}
            ],
            u'node_id': u'fakevm',
            u'node_instances': 9
        }
    ]

    _assert_summary_equal(results, expected)


def test_basic_summary_paged(prepared_manager):
    results = prepared_manager.client.summary.blueprints.get(
        _target_field='tenant_name',
        _all_tenants=True,
        _size=2,
        _offset=0,
    ).items

    expected = [
        {u'blueprints': 3, u'tenant_name': u'test1'},
        {u'blueprints': 3, u'tenant_name': u'default_tenant'},
    ]

    _assert_summary_equal(results, expected)

    # And the second page, please
    results = prepared_manager.client.summary.blueprints.get(
        _target_field='tenant_name',
        _all_tenants=True,
        _size=2,
        _offset=2,
        _sort='blueprint_id',
    ).items

    expected = [
        {u'blueprints': 3, u'tenant_name': u'test2'},
    ]

    _assert_summary_equal(results, expected)


def test_cli_blueprints_summary(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy blueprints summary visibility --json'
        ).stdout
    )
    expected = [{"blueprints": 3, "visibility": "tenant"}]
    _assert_summary_equal(results, expected)


def test_cli_blueprints_summary_subfield(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy blueprints summary tenant_name visibility '
            '--json --all-tenants'
        ).stdout
    )
    # None values are totals
    expected = [
        {u'tenant_name': u'test1', u'blueprints': 3,
         u'visibility': u'tenant'},
        {u'tenant_name': u'test1', u'blueprints': 3,
         u'visibility': None},
        {u'tenant_name': u'test2', u'blueprints': 3,
         u'visibility': u'tenant'},
        {u'tenant_name': u'test2', u'blueprints': 3,
         u'visibility': None},
        {u'tenant_name': u'default_tenant', u'blueprints': 3,
         u'visibility': u'tenant'},
        {u'tenant_name': u'default_tenant', u'blueprints': 3,
         u'visibility': None}
    ]
    _assert_summary_equal(results, expected)


def test_cli_blueprints_summary_subfield_non_json(prepared_manager):
    """
        Ensure that 'TOTAL' appears in non-json output (this should be in
        place of the None used in the json output).
    """
    results = prepared_manager.run_command(
        'cfy blueprints summary tenant_name visibility --all-tenants'
    ).stdout
    assert 'TOTAL' in results


def test_cli_deployments_summary(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy deployments summary blueprint_id --json'
        ).stdout
    )
    expected = [
        {"deployments": 2, "blueprint_id": "small"},
        {"deployments": 1, "blueprint_id": "multivm"},
        {"deployments": 3, "blueprint_id": "relations"}
    ]
    _assert_summary_equal(results, expected)


def test_cli_deployments_summary_subfield(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy deployments summary tenant_name blueprint_id '
            '--json --all-tenants'
        ).stdout
    )
    # None values are totals
    expected = [
        {"tenant_name": "test1", "deployments": 3,
         "blueprint_id": "multivm"},
        {"tenant_name": "test1", "deployments": 1,
         "blueprint_id": "small"},
        {"tenant_name": "test1", "deployments": 2,
         "blueprint_id": "relations"},
        {"tenant_name": "test1", "deployments": 6,
         "blueprint_id": None},
        {"tenant_name": "test2", "deployments": 2,
         "blueprint_id": "multivm"},
        {"tenant_name": "test2", "deployments": 1,
         "blueprint_id": "relations"},
        {"tenant_name": "test2", "deployments": 3,
         "blueprint_id": "small"},
        {"tenant_name": "test2", "deployments": 6,
         "blueprint_id": None},
        {"tenant_name": "default_tenant", "deployments": 1,
         "blueprint_id": "multivm"},
        {"tenant_name": "default_tenant", "deployments": 3,
         "blueprint_id": "relations"},
        {"tenant_name": "default_tenant", "deployments": 2,
         "blueprint_id": "small"},
        {"tenant_name": "default_tenant", "deployments": 6,
         "blueprint_id": None}
    ]
    _assert_summary_equal(results, expected)


def test_cli_deployments_summary_subfield_non_json(prepared_manager):
    """
        Ensure that 'TOTAL' appears in non-json output (this should be in
        place of the None used in the json output).
    """
    results = prepared_manager.run_command(
        'cfy deployments summary tenant_name blueprint_id --all-tenants'
    ).stdout
    assert 'TOTAL' in results


def test_cli_executions_summary(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy executions summary workflow_id --json'
        ).stdout
    )
    expected = [
        {"workflow_id": "create_deployment_environment", "executions": 6},
        {"workflow_id": "install", "executions": 6},
        {"workflow_id": "upload_blueprint", "executions": 3},
    ]
    _assert_summary_equal(results, expected)


def test_cli_executions_summary_subfield(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy executions summary tenant_name workflow_id '
            '--json --all-tenants'
        ).stdout
    )
    # None values are totals
    expected = [
        {"tenant_name": "test1",
         "workflow_id": "create_deployment_environment", "executions": 6},
        {"tenant_name": "test1",
         "workflow_id": "install", "executions": 6},
        {"tenant_name": "test1",
         "workflow_id": "upload_blueprint", "executions": 3},
        {"tenant_name": "test1",
         "workflow_id": None, "executions": 15},
        {"tenant_name": "test2",
         "workflow_id": "create_deployment_environment", "executions": 6},
        {"tenant_name": "test2",
         "workflow_id": "install", "executions": 6},
        {"tenant_name": "test2",
         "workflow_id": "upload_blueprint", "executions": 3},
        {"tenant_name": "test2",
         "workflow_id": None, "executions": 15},
        {"tenant_name": "default_tenant",
         "workflow_id": "create_deployment_environment", "executions": 6},
        {"tenant_name": "default_tenant",
         "workflow_id": "install", "executions": 6},
        {"tenant_name": "default_tenant",
         "workflow_id": "upload_blueprint", "executions": 3},
        {"tenant_name": "default_tenant",
         "workflow_id": None, "executions": 15}
    ]
    _assert_summary_equal(results, expected)


def test_cli_executions_summary_subfield_non_json(prepared_manager):
    """
        Ensure that 'TOTAL' appears in non-json output (this should be in
        place of the None used in the json output).
    """
    results = prepared_manager.run_command(
        'cfy executions summary tenant_name workflow_id --all-tenants'
    ).stdout
    assert 'TOTAL' in results


def test_cli_nodes_summary(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy nodes summary deployment_id --json'
        ).stdout
    )
    expected = [
        {"deployment_id": "small1", "nodes": 1},
        {"deployment_id": "small0", "nodes": 1},
        {"deployment_id": "relations2", "nodes": 5},
        {"deployment_id": "relations1", "nodes": 5},
        {"deployment_id": "relations0", "nodes": 5},
        {"deployment_id": "multivm0", "nodes": 2}
    ]
    _assert_summary_equal(results, expected)


def test_cli_nodes_summary_subfield(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy nodes summary tenant_name deployment_id '
            '--json --all-tenants'
        ).stdout
    )
    # None values are totals
    expected = [
        {"tenant_name": "test1", "deployment_id": "relations1",
         "nodes": 5},
        {"tenant_name": "test1", "deployment_id": "multivm0",
         "nodes": 2},
        {"tenant_name": "test1", "deployment_id": "multivm2",
         "nodes": 2},
        {"tenant_name": "test1", "deployment_id": "multivm1",
         "nodes": 2},
        {"tenant_name": "test1", "deployment_id": "relations0",
         "nodes": 5},
        {"tenant_name": "test1", "deployment_id": "small0",
         "nodes": 1},
        {"tenant_name": "test1", "deployment_id": None,
         "nodes": 17},
        {"tenant_name": "test2", "deployment_id": "small0",
         "nodes": 1},
        {"tenant_name": "test2", "deployment_id": "small1",
         "nodes": 1},
        {"tenant_name": "test2", "deployment_id": "relations0",
         "nodes": 5},
        {"tenant_name": "test2", "deployment_id": "multivm0",
         "nodes": 2},
        {"tenant_name": "test2", "deployment_id": "small2",
         "nodes": 1},
        {"tenant_name": "test2", "deployment_id": "multivm1",
         "nodes": 2},
        {"tenant_name": "test2", "deployment_id": None,
         "nodes": 12},
        {"tenant_name": "default_tenant", "deployment_id": "multivm0",
         "nodes": 2},
        {"tenant_name": "default_tenant", "deployment_id": "relations1",
         "nodes": 5},
        {"tenant_name": "default_tenant", "deployment_id": "small1",
         "nodes": 1},
        {"tenant_name": "default_tenant", "deployment_id": "relations2",
         "nodes": 5},
        {"tenant_name": "default_tenant", "deployment_id": "small0",
         "nodes": 1},
        {"tenant_name": "default_tenant", "deployment_id": "relations0",
         "nodes": 5},
        {"tenant_name": "default_tenant", "deployment_id": None,
         "nodes": 19}
    ]
    _assert_summary_equal(results, expected)


def test_cli_nodes_summary_subfield_non_json(prepared_manager):
    """
        Ensure that 'TOTAL' appears in non-json output (this should be in
        place of the None used in the json output).
    """
    results = prepared_manager.run_command(
        'cfy nodes summary tenant_name deployment_id --all-tenants'
    ).stdout
    assert 'TOTAL' in results


def test_cli_node_instances_summary(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy node-instances summary node_id --json'
        ).stdout
    )
    expected = [
        {"node_id": "fakeapp1", "node_instances": 6},
        {"node_id": "fakevm2", "node_instances": 4},
        {"node_id": "fakeplatformthing1", "node_instances": 3},
        {"node_id": "fakevm", "node_instances": 9},
        {"node_id": "fakeappconfig1", "node_instances": 3}
    ]
    _assert_summary_equal(results, expected)


def test_cli_node_instances_summary_subfield(prepared_manager):
    results = json.loads(
        prepared_manager.run_command(
            'cfy node-instances summary tenant_name node_id '
            '--json --all-tenants'
        ).stdout
    )
    # None values are totals
    expected = [
        {"tenant_name": "test1", "node_id": "fakeapp1",
         "node_instances": 4},
        {"tenant_name": "test1", "node_id": "fakeappconfig1",
         "node_instances": 2},
        {"tenant_name": "test1", "node_id": "fakeplatformthing1",
         "node_instances": 2},
        {"tenant_name": "test1", "node_id": "fakevm",
         "node_instances": 8},
        {"tenant_name": "test1", "node_id": "fakevm2",
         "node_instances": 5},
        {"tenant_name": "test1", "node_id": None,
         "node_instances": 21},
        {"tenant_name": "test2", "node_id": "fakeapp1",
         "node_instances": 2},
        {"tenant_name": "test2", "node_id": "fakeappconfig1",
         "node_instances": 1},
        {"tenant_name": "test2", "node_id": "fakeplatformthing1",
         "node_instances": 1},
        {"tenant_name": "test2", "node_id": "fakevm",
         "node_instances": 7},
        {"tenant_name": "test2", "node_id": "fakevm2",
         "node_instances": 3},
        {"tenant_name": "test2", "node_id": None,
         "node_instances": 14},
        {"tenant_name": "default_tenant", "node_id": "fakeapp1",
         "node_instances": 6},
        {"tenant_name": "default_tenant", "node_id": "fakeappconfig1",
         "node_instances": 3},
        {"tenant_name": "default_tenant", "node_id": "fakeplatformthing1",
         "node_instances": 3},
        {"tenant_name": "default_tenant", "node_id": "fakevm",
         "node_instances": 9},
        {"tenant_name": "default_tenant", "node_id": "fakevm2",
         "node_instances": 4},
        {"tenant_name": "default_tenant", "node_id": None,
         "node_instances": 25}
    ]
    _assert_summary_equal(results, expected)


def test_cli_node_instances_summary_subfield_non_json(prepared_manager):
    """
        Ensure that 'TOTAL' appears in non-json output (this should be in
        place of the None used in the json output).
    """
    results = prepared_manager.run_command(
        'cfy node-instances summary tenant_name node_id --all-tenants'
    ).stdout
    assert 'TOTAL' in results
