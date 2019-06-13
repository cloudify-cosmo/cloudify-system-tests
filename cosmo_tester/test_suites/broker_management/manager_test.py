import json


def test_broker_management(brokers_and_manager, logger):
    # All in one test for speed until such time as complexity of these
    # operations increases to the point that extra tests are needed.
    broker1, broker2, manager = brokers_and_manager
    manager.put_remote_file(
        local_path=broker1.ca_path,
        remote_path='/tmp/rabbit.ca',
    )

    manager.additional_install_config = {
        'rabbitmq': {
            'ca_path': '/tmp/rabbit.ca',
            'cluster_members': {
                broker1.hostname: {
                    'default': str(broker1.private_ip_address),
                }
            }
        },
        'services_to_install': ['database_service', 'manager_service'],
    }
    manager.bootstrap()

    manager.enter_sanity_mode()

    expected_1 = {
        'port': 5671,
        'networks': {'default': str(broker1.private_ip_address)},
        'name': broker1.hostname,
    }
    broker_2_nets = {'default': str(broker2.private_ip_address),
                     'testnet': '192.0.2.4'}
    expected_2 = {
        'port': 5671,
        'networks': broker_2_nets,
        'name': broker2.hostname,
    }

    logger.info('Confirming list functionality.')
    brokers_list = list_brokers(manager)
    assert brokers_list == [expected_1]
    logger.info('Listing check passed.')

    logger.info('Confirming add functionality.')
    manager.run_command(
        'cfy cluster brokers add {name} {ip} -n "{net}"'.format(
            name=broker2.hostname,
            ip=str(broker2.private_ip_address),
            net=json.dumps(broker_2_nets),
        )
    )
    brokers_list = list_brokers(manager)
    assert len(brokers_list) == 2
    assert expected_1 in brokers_list
    assert expected_2 in brokers_list
    logger.info('Adding broker succeeded.')

    logger.info('Confirming removal functionality.')
    manager.run_command(
        'cfy cluster brokers remove {name}'.format(
            name=broker1.hostname,
        )
    )
    brokers_list = list_brokers(manager)
    assert brokers_list == [expected_2]
    logger.info('Removing broker succeeded.')


def list_brokers(manager):
    return json.loads(
        manager.run_command(
            'cfy cluster brokers list --json 2>/dev/null | cat'
        )
    )
