import json
import time


def get_broker_listing(broker, prefix='rabbit@'):
    with broker.ssh() as broker_ssh:
        brokers_list_output = broker_ssh.run('cfy_manager brokers-list')
    broker_lines = [line for line in brokers_list_output.splitlines()
                    if prefix in line]
    brokers = {}
    for line in broker_lines:
        line = line.split('|')
        broker_name = line[1].strip()[len(prefix):]
        broker_running = line[2].strip()
        broker_alarms = line[3].strip()
        brokers[broker_name] = {
            'running': broker_running == 'True',
            'alarms': broker_alarms,
        }
    return brokers


def manager_list_brokers(manager):
    return json.loads(
        manager.run_command(
            'cfy cluster brokers list --json 2>/dev/null | cat'
        )
    )


def add_to_hosts(target_broker, new_entry_brokers):
    new_entry = 'echo "{ip} {hostname}" | sudo tee -a /etc/hosts'
    with target_broker.ssh() as target_ssh:
        for other_broker in new_entry_brokers:
            target_ssh.run(new_entry.format(
                ip=other_broker.private_ip_address,
                hostname=other_broker.hostname,
            ))


def join_cluster(new_broker, cluster_member):
    with new_broker.ssh() as broker_ssh:
        broker_ssh.run('cfy_manager brokers-add -j {cluster_node}'.format(
            cluster_node=cluster_member.hostname,
        ))


def get_cluster_listing(cluster_brokers, down=()):
    cluster_listing = get_broker_listing(cluster_brokers[0])
    for other_broker in cluster_brokers[1:]:
        if other_broker.hostname not in down:
            assert cluster_listing == get_broker_listing(other_broker)
    assert len(cluster_listing) == len(cluster_brokers)
    for broker in cluster_brokers:
        assert broker.hostname in cluster_listing
    return cluster_listing


def kill_node(broker):
    with broker.ssh() as broker_ssh:
        broker_ssh.run('sudo service cloudify-rabbitmq stop')
        broker_ssh.run('sudo shutdown -h now &')


def test_list(brokers, logger):
    # Testing multiple lists in one test because each deploy of brokers takes
    # several minutes
    logger.info('Checking single broker only lists itself.')
    get_cluster_listing([brokers[0]])
    logger.info('Single broker listing is correct.')

    logger.info('Adding second broker.')
    add_to_hosts(brokers[1], [brokers[0]])
    add_to_hosts(brokers[0], [brokers[1]])
    join_cluster(brokers[1], brokers[0])
    logger.info('Second broker added.')

    logger.info('Checking multiple brokers list correctly.')
    cluster_listing = get_cluster_listing([brokers[0], brokers[1]])
    for broker in cluster_listing.values():
        assert broker['running']
    logger.info('Multiple brokers listing is correct.')

    logger.info('Checking broker alarm')
    with brokers[1].ssh() as broker_ssh:
        broker_ssh.run('sudo rabbitmqctl set_disk_free_limit 99999GB')
    logger.info('Waiting for disk alarm to trigger.')
    for i in range(5):
        time.sleep(2)
        cluster_listing = get_cluster_listing([brokers[0], brokers[1]])
        first_broker_alarms = cluster_listing[brokers[0].hostname]['alarms']
        second_broker_alarms = cluster_listing[brokers[1].hostname]['alarms']
        if second_broker_alarms == 'disk_free_alarm':
            break
    assert not first_broker_alarms, (
        'First broker should have no alarms, but had: {alarms}'.format(
            alarms=first_broker_alarms,
        )
    )
    assert second_broker_alarms == 'disk_free_alarm', (
        'Second broker should have disk_free_alarm, but had: {alarms}'.format(
            alarms=second_broker_alarms,
        )
    )
    logger.info('Broker alarms are correct.')

    logger.info('Checking single node down')
    # Adding another node first or we'll break the cluster
    add_to_hosts(brokers[2], [brokers[0]])
    add_to_hosts(brokers[2], [brokers[1]])
    add_to_hosts(brokers[0], [brokers[2]])
    add_to_hosts(brokers[1], [brokers[2]])
    join_cluster(brokers[2], brokers[0])
    kill_node(brokers[2])
    cluster_listing = get_cluster_listing(brokers, down=[brokers[2].hostname])
    assert cluster_listing[brokers[0].hostname]['running']
    assert cluster_listing[brokers[1].hostname]['running']
    assert not cluster_listing[brokers[2].hostname]['running']
    logger.info('Single node down running state is correct.')

    logger.info('Checking cluster down')
    kill_node(brokers[1])
    with brokers[0].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-list 2>&1 || true'
        ).lower()
        # Make sure we make some indication of possible cluster failure in the
        # output
        assert 'cluster' in result
        assert 'failed' in result
    logger.info('Cluster down check successful.')


def test_auth_fail(broker, logger):
    with broker.ssh() as broker_ssh:
        broker_ssh.sudo(
            "sed -i 's/password: .*/password: wrongpassword/' "
            "/etc/cloudify/config.yaml"
        )
        result = broker_ssh.run(
            'cfy_manager brokers-list 2>&1 || true'
        ).lower()
        # Make sure we indicate something about auth failure in the output
        assert 'login' in result
        assert 'fail' in result


def test_add(brokers, logger):
    logger.info('Preparing hosts files')
    add_to_hosts(brokers[0], brokers[1:])
    add_to_hosts(brokers[1], [brokers[0], brokers[2]])
    # Deliberately not adding first broker address to last broker
    add_to_hosts(brokers[2], [brokers[1]])
    logger.info('Hosts files prepared.')

    logger.info('Attempting to add node with stopped rabbit.')
    with brokers[2].ssh() as broker_ssh:
        broker_ssh.sudo('rabbitmqctl stop_app')
    with brokers[0].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-add -j {node} || true'.format(
                node=brokers[2].hostname,
            )
        ).lower()
        assert 'start' in result
        assert 'node' in result
    get_cluster_listing([brokers[0]])
    with brokers[2].ssh() as broker_ssh:
        broker_ssh.sudo('rabbitmqctl start_app')
    logger.info('Correct failure attempting to add stopped rabbit.')

    logger.info('Adding node to cluster.')
    with brokers[0].ssh() as broker_ssh:
        broker_ssh.run('cfy_manager brokers-add -j {node}'.format(
            node=brokers[1].hostname,
        ))
    get_cluster_listing([brokers[0], brokers[1]])
    logger.info('Adding node successful.')

    logger.info('Attempting to add from clustered node.')
    with brokers[0].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-add -j {node} || true'.format(
                node=brokers[2].hostname,
            )
        ).lower()
        assert 'in' in result
        assert 'cluster' in result
        assert 'run' in result
        assert 'joining' in result
        assert 'not' in result
        assert 'existing' in result
    logger.info('Correctly failed to join from cluster member.')

    logger.info('Attempting to add unresolvable node.')
    with brokers[2].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-add -j {node} || true'.format(
                node=brokers[0].hostname,
            )
        ).lower()
        assert 'resolvable' in result
    logger.info('Unresolvable join failed correctly.')

    logger.info('Attempting to add with different erlang cookie.')
    with brokers[2].ssh() as broker_ssh:
        broker_ssh.run('cfy_manager remove --force')
        broker_ssh.run(
            "sudo sed -i 's/erlang_cookie:.*/erlang_cookie: different/' "
            "/etc/cloudify/config.yaml"
        )
        broker_ssh.run('cfy_manager install')
        result = broker_ssh.run(
            'cfy_manager brokers-add -j {node} || true'.format(
                node=brokers[1].hostname,
            )
        ).lower()
        assert 'erlang' in result
        assert 'cookie' in result
    logger.info('Incorrect erlang cookie gave correct error.')

    logger.info('Attempting to join unreachable node.')
    kill_node(brokers[1])
    with brokers[2].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-add -j {node} || true'.format(
                node=brokers[1].hostname,
            )
        ).lower()
        assert 'cannot' in result
        assert 'connect' in result
    logger.info('Correct error trying to join unreachable node.')


def test_remove(brokers, logger):
    logger.info('Preparing cluster.')
    add_to_hosts(brokers[0], brokers[1:])
    add_to_hosts(brokers[1], [brokers[0], brokers[2]])
    add_to_hosts(brokers[2], brokers[:2])
    join_cluster(brokers[1], brokers[0])
    join_cluster(brokers[2], brokers[0])
    logger.info('Cluster prepared.')

    logger.info('Attempting to remove active node.')
    with brokers[0].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-remove -r {node} 2>&1 || true'.format(
                node=brokers[1].hostname,
            )
        ).lower()
        assert 'must' in result
        assert 'shut down' in result
    logger.info('Active node removal check successful.')

    logger.info('Attempting to remove dead node.')
    kill_node(brokers[1])
    get_cluster_listing(brokers, down=[brokers[1].hostname])
    with brokers[0].ssh() as broker_ssh:
        broker_ssh.run(
            'cfy_manager brokers-remove -r {node} 2>&1 || true'.format(
                node=brokers[1].hostname,
            )
        )
    get_cluster_listing([brokers[0], brokers[2]])
    logger.info('Dead node removed successfully.')

    logger.info('Attempting to remove dead node... again.')
    with brokers[0].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-remove -r {node} 2>&1 || true'.format(
                node=brokers[1].hostname,
            )
        ).lower()
        assert 'not found' in result
        # Make sure we list valid nodes
        assert brokers[0].hostname in result
        assert brokers[2].hostname in result
    logger.info('Removing missing node gave correct result.')

    logger.info('Cluster failure recovery test.')
    kill_node(brokers[2])
    with brokers[0].ssh() as broker_ssh:
        result = broker_ssh.run(
            'cfy_manager brokers-remove -r {node} 2>&1 || true'.format(
                node=brokers[2].hostname,
            )
        ).lower()
        assert 'cluster' in result
        assert 'failed' in result

        # Expected result, now we will recover
        broker_ssh.sudo('systemctl restart cloudify-rabbitmq')
        broker_ssh.run(
            'cfy_manager brokers-remove -r {node}'.format(
                node=brokers[2].hostname,
            )
        )
    get_cluster_listing([brokers[0]])
    logger.info('Cluster failure recovery successful.')


def test_broker_management(brokers_and_manager, logger):
    # All in one test for speed until such time as complexity of these
    # operations increases to the point that extra tests are needed.
    broker1, broker2, manager = brokers_and_manager

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
    brokers_list = manager_list_brokers(manager)
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
    brokers_list = manager_list_brokers(manager)
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
    brokers_list = manager_list_brokers(manager)
    assert brokers_list == [expected_2]
    logger.info('Removing broker succeeded.')
