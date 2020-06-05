def check_managers(mgr1, mgr2, example):
    # Check each manager can run workflows independently
    mgr2.run_command('sudo systemctl stop cloudify-mgmtworker')
    example.uninstall()
    mgr2.run_command('sudo systemctl start cloudify-mgmtworker')
    mgr1.run_command('sudo systemctl stop cloudify-mgmtworker')
    example.install()
    example.check_files()
    mgr1.run_command('sudo systemctl start cloudify-mgmtworker')
