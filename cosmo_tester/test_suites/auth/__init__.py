def check_manager_using_correct_idp(manager, logger, expected):
    logger.info('Confirming %s IDP is being used on %s.',
                expected, manager.ip_address)
    assert manager.client.idp.get() == expected
