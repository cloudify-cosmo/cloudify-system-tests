
import json
import os
import uuid

from influxdb import InfluxDBClient
import pytest
import requests
from retrying import retry

from cosmo_tester.framework import git_helper




CLOUDIFY_HELLO_WORLD_EXAMPLE_URL = "https://github.com/cloudify-cosmo/" \
                                   "cloudify-hello-world-example.git"


@retry(stop_max_attempt_number=10, wait_fixed=5000)
def assert_webserver_running(http_endpoint, logger):
    logger.info(
            'Verifying web server is running on: {0}'.format(http_endpoint))
    server_response = requests.get(http_endpoint, timeout=15)
    if server_response.status_code != 200:
        pytest.fail('Unexpected status code: {}'.format(
                server_response.status_code))


def assert_metrics(deployment_id, influx_host_ip, logger):
    logger.info('Verifying deployment metrics..')
    influx_client = InfluxDBClient(influx_host_ip, 8086,
                                   'root', 'root', 'cloudify')
    try:
        # select monitoring events for deployment from
        # the past 5 seconds. a NameError will be thrown only if NO
        # deployment events exist in the DB regardless of time-span
        # in query.
        influx_client.query('select * from /^{0}\./i '
                            'where time > now() - 5s'
                            .format(deployment_id))
    except NameError as e:
        pytest.fail('Monitoring events list for deployment with ID {0} were'
                    ' not found on influxDB. error is: {1}'
                    .format(deployment_id, e))


def assert_events(deployment_id, manager, logger):
    logger.info('Verifying deployment events..')
    executions = manager.client.executions.list(deployment_id=deployment_id)
    events, total_events = manager.client.events.get(executions[0].id)
    assert len(events) > 0, 'There are no events for deployment: {0}'.format(
            deployment_id)


def test_hello_world_on_centos_7(cfy, manager, attributes, tmpdir, logger):
    hello_world_path = git_helper.clone(
            CLOUDIFY_HELLO_WORLD_EXAMPLE_URL,
            str(tmpdir),
            branch='CFY-6157-adjust-openstack-to-simple-mgr-blueprint')
    blueprint_file = hello_world_path / 'openstack-blueprint.yaml'
    unique_id = 'hello-{0}'.format(str(uuid.uuid4()))
    logger.info('Uploading blueprint: %s [id=%s]', blueprint_file, unique_id)
    manager.client.blueprints.upload(blueprint_file, unique_id)
    inputs = {
        'agent_user': attributes.centos7_username,
        'image': attributes.centos7_image_name,
        'floating_network_id': attributes.floating_network_id,
        'key_pair_name': attributes.keypair_name,
        'private_key_path': manager.remote_private_key_path,
        'flavor': attributes.medium_flavor_name,
        'network_name': attributes.network_name
    }
    logger.info('Creating deployment [id=%s] with the following inputs:%s%s',
                unique_id, os.linesep, json.dumps(inputs, indent=2))
    deployment = manager.client.deployments.create(
            unique_id, unique_id, inputs=inputs)
    cfy.deployments.list()
    logger.info('Installing deployment...')
    cfy.executions.start.install(['-d', deployment.id])
    outputs = manager.client.deployments.outputs.get(deployment.id)['outputs']
    logger.info('Deployment outputs: %s%s',
                os.linesep, json.dumps(outputs, indent=2))
    assert_webserver_running(outputs['http_endpoint'], logger)
    assert_events(deployment.id, manager, logger)
    assert_metrics(deployment.id, manager.ip_address, logger)

    logger.info('Uninstalling deployment...')
    cfy.executions.start.uninstall(['-d', deployment.id])

    logger.info('Deleting deployment...')
    manager.client.deployments.delete(deployment.id)
