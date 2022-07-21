def test_manager_bootstrap_and_deployment(bootstrap_test_manager):

    node = bootstrap_test_manager
    for inst_config in node.basic_install_config, node.install_config:
        inst_config['mgmtworker'] = {}
        inst_config['mgmtworker']['extra_env'] = {"CFY_EXEC_TEMP": "/tmp"}
    bootstrap_test_manager.bootstrap(include_sanity=True)
