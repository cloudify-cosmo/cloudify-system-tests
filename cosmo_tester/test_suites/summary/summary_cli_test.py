import json

from . import _assert_summary_equal


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
