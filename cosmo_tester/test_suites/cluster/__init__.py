def check_managers(mgr1, mgr2):
    # Run sanity checks on each manager independently to confirm they can
    # independently run workflows
    mgr2.run_command('sudo systemctl stop cloudify-mgmtworker')
    mgr1.run_command('cfy_manager sanity-check')
    mgr2.run_command('sudo systemctl start cloudify-mgmtworker')
    mgr1.run_command('sudo systemctl stop cloudify-mgmtworker')
    mgr2.run_command('cfy_manager sanity-check')
    mgr1.run_command('sudo systemctl start cloudify-mgmtworker')
