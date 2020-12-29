def validate_agents(manager, tenant):
    validate_agents_wf = manager.run_command(
        'cfy agents validate --tenant-name {}'.format(tenant)).stdout
    assert 'Task succeeded' in validate_agents_wf
