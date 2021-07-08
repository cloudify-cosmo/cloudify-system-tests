import time


def check_managers(mgr1, mgr2, example):
    # Check each manager can run workflows independently
    mgr2.run_command('sudo supervisorctl stop cloudify-mgmtworker')
    time.sleep(3)
    example.uninstall(delete_dep=False)
    mgr2.run_command('sudo supervisorctl start cloudify-mgmtworker')
    mgr1.run_command('sudo supervisorctl stop cloudify-mgmtworker')
    time.sleep(3)
    example.install()
    example.check_files()
    mgr1.run_command('sudo supervisorctl start cloudify-mgmtworker')
    # Uninstall to not contaminate other tests
    example.uninstall()
