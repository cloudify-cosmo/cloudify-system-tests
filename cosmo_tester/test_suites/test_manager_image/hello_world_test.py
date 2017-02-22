import json
import os
import re
import uuid

import pytest
import requests
from influxdb import InfluxDBClient
from retrying import retry
from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers

from cosmo_tester.framework import git_helper

CLOUDIFY_HELLO_WORLD_EXAMPLE_URL = "https://github.com/cloudify-cosmo/" \
                                   "cloudify-hello-world-example.git"


class HelloWorldExample(object):

    def __init__(self, cfy, manager, attributes, ssh_key, logger, tmpdir):
        self.attributes = attributes
        self.logger = logger
        self.manager = manager
        self.cfy = cfy
        self.tmpdir = tmpdir
        self._ssh_key = ssh_key
        self._cleanup_required = False
        self._deployment_id = None
        self.inputs = {
            'floating_network_id': self.attributes.floating_network_id,
            'key_pair_name': self.attributes.keypair_name,
            'private_key_path': self.manager.remote_private_key_path,
            'flavor': self.attributes.medium_flavor_name,
            'network_name': self.attributes.network_name
        }
        self.disable_iptables = False

    @property
    def cleanup_required(self):
        return self._cleanup_required

    def verify_all(self):
        hello_world_path = git_helper.clone(
                CLOUDIFY_HELLO_WORLD_EXAMPLE_URL,
                str(self.tmpdir))
        blueprint_file = hello_world_path / 'openstack-blueprint.yaml'
        unique_id = 'hello-{0}'.format(str(uuid.uuid4()))
        self.logger.info(
            'Uploading blueprint: %s [id=%s]', blueprint_file, unique_id)
        self.manager.client.blueprints.upload(blueprint_file, unique_id)
        self.logger.info(
            'Creating deployment [id=%s] with the following inputs:%s%s',
                    unique_id, os.linesep, json.dumps(self.inputs, indent=2))
        deployment = self.manager.client.deployments.create(
                unique_id, unique_id, inputs=self.inputs)
        self._deployment_id = deployment.id
        self.cfy.deployments.list()
        self.logger.info('Installing deployment...')
        self._cleanup_required = True
        self.cfy.executions.start.install(['-d', deployment.id])
        outputs = self.manager.client.deployments.outputs.get(deployment.id)['outputs']
        self.logger.info('Deployment outputs: %s%s',
                         os.linesep, json.dumps(outputs, indent=2))

        http_endpoint = outputs['http_endpoint']
        if self.disable_iptables:
            self._disable_iptables(http_endpoint)

        assert_webserver_running(http_endpoint, self.logger)
        assert_events(deployment.id, self.manager, self.logger)
        assert_metrics(deployment.id, self.manager.ip_address, self.logger)

        self.logger.info('Uninstalling deployment...')
        self.cfy.executions.start.uninstall(['-d', deployment.id])
        self._cleanup_required = False

        self.logger.info('Deleting deployment...')
        self.manager.client.deployments.delete(deployment.id)

    def cleanup(self):
        self.logger.info('Performing hello world cleanup..')
        self.cfy.executions.start.uninstall(
                ['-d', self._deployment_id, '-p', 'ignore_failure=true', '-f'])

    @retry(stop_max_attempt_number=3, wait_fixed=10000)
    def _disable_iptables(self, http_endpoint):
        self.logger.info('Disabling iptables on hello world vm..')
        ip = re.findall(r'[0-9]+(?:\.[0-9]+){3}', http_endpoint)[0]
        self.logger.info('Hello world vm IP address is: %s', ip)
        with fabric_context_managers.settings(
                host_string=ip,
                user=self.inputs['agent_user'],
                key_filename=self._ssh_key.private_key_path,
                connections_attempts=3,
                abort_on_prompts=True):
            fabric_api.sudo('sudo service iptables save')
            fabric_api.sudo('sudo service iptables stop')
            fabric_api.sudo('sudo chkconfig iptables off')


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


@pytest.fixture(scope='function')
def hello_world(cfy, manager, attributes, ssh_key, tmpdir, logger):

    hw = HelloWorldExample(cfy, manager, attributes, ssh_key, logger, tmpdir)
    yield hw
    if hw.cleanup_required:
        logger.info('Hello world cleanup required..')
        hw.cleanup()


def test_hello_world_on_centos_7(hello_world, attributes):
    hello_world.inputs.update({
        'agent_user': attributes.centos7_username,
        'image': attributes.centos7_image_name,
    })
    hello_world.verify_all()


def test_hello_world_on_centos_6(hello_world, attributes):
    hello_world.inputs.update({
        'agent_user': attributes.centos6_username,
        'image': attributes.centos6_image_name,
    })
    hello_world.disable_iptables = True
    hello_world.verify_all()


def test_hello_world_on_ubuntu_14_04(hello_world, attributes):
    hello_world.inputs.update({
        'agent_user': attributes.ubuntu_username,
        'image': attributes.ubuntu_14_04_image_name,
    })
    hello_world.verify_all()


# def test_logger(logger):
#     logger.info('hello logger!')

# Not yet supported.
# def test_hello_world_on_ubuntu_16_04(hello_world, attributes):
#     hello_world.inputs.update({
#         'agent_user': attributes.ubuntu_username,
#         'image': attributes.ubuntu_16_04_image_name,
#     })
#     hello_world.verify_all()
