########
# Copyright (c) 2019 Cloudify Platform Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import pytest

from .test_hosts import (
    TestHosts,
    BootstrapBasedCloudifyManagers,
    DistributedInstallationCloudifyManager
)
from cosmo_tester.framework.util import prepare_and_get_test_tenant
from cosmo_tester.framework.examples.nodecellar import NodeCellarExample
from cosmo_tester.framework.examples.hello_world import centos_hello_world
from cosmo_tester.framework.cfy_helper import TENANT_NAME


SKIP_SANITY = {'skip_sanity': 'true'}
DATABASE_SERVICES_TO_INSTALL = ['database_service']
QUEUE_SERVICES_TO_INSTALL = ['queue_service']
MANAGER_SERVICES_TO_INSTALL = ['manager_service']


@pytest.fixture(scope='module')
def image_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger, request=request)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


@pytest.fixture(scope='module')
def image_based_manager_without_plugins(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    hosts = TestHosts(
            cfy, ssh_key, module_tmpdir, attributes, logger, request=request,
            upload_plugins=False)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


@pytest.fixture(scope='module')
def bootstrap_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Bootstraps a cloudify manager on a VM in rackspace OpenStack."""
    hosts = BootstrapBasedCloudifyManagers(
            cfy, ssh_key, module_tmpdir, attributes, logger)
    try:
        hosts.create()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()


@pytest.fixture(scope='function')
def distributed_installation(cfy, ssh_key, module_tmpdir, attributes, logger,
                             request):
    """
    Bootstraps a cloudify manager distributed installation based on the request
    parameters

    If request.param has a 'cluster' value: 5 nodes are built (1 DB 1 Queue
    3 managers)

    If request.param has a 'sanity' value: 6 nodes are built (1 DB 1 Queue
    3 managers and an AIO manager)

    With every call 'template_inputs' and 'tf_template' can be passed in when
    creating the TestHosts object

    If you need to have your own preconfigure_callback it can be supplied and
    will run before the cluster one
    """
    cluster, sanity, template_inputs, tf_template = False, False, None, None
    supplied_preconfigure_callback = None
    # request isn't created with a 'param' attribute if no params are sent
    if hasattr(request, 'param'):
        cluster = 'cluster' in request.param
        sanity = 'sanity' in request.param
        template_inputs = request.param.get('template_inputs', None)
        tf_template = request.param.get('tf_template', None)
        supplied_preconfigure_callback =\
            request.param.get('supplied_preconfigure_callback', None)

    # The preconfigure callback populates the files structure prior to the BS
    def _preconfigure_callback_cluster(distributed_installation):
        # First run any preconfigure callbacks received since it can override
        # ours
        if supplied_preconfigure_callback:
            supplied_preconfigure_callback(distributed_installation)
        # Updating the database VM first
        distributed_installation[0].additional_install_config.update({
            'sanity': SKIP_SANITY,
            'postgresql_server': {
                'enable_remote_connections': 'true',
                'postgres_password': 'postgres'
            },
            'services_to_install': DATABASE_SERVICES_TO_INSTALL
        })
        # Updating the RabbitMQ machine
        distributed_installation[1].additional_install_config.update({
            'nodename': 'localhost',
            'services_to_install': QUEUE_SERVICES_TO_INSTALL
        })
        # Updating the 1st manager machine
        distributed_installation[2].additional_install_config.update({
            'sanity': SKIP_SANITY,
            'rabbitmq': {
                'cluster_members': {
                    'localhost': {
                        'default': str(
                            distributed_installation[1].private_ip_address),
                    }
                }
            },
            'postgresql_client': {
                'host': str(distributed_installation[0].private_ip_address),
                'postgres_password': 'postgres'
            },
            'services_to_install': MANAGER_SERVICES_TO_INSTALL
        })
        if cluster:
            # Updating both VMs to point to the master
            distributed_installation[3].additional_install_config.update({
                'sanity': SKIP_SANITY,
                'rabbitmq': {
                    'cluster_members': {
                        'localhost': {
                            'default': str(
                                distributed_installation[1].private_ip_address),
                        }
                    }
                },
                'cluster': {
                    'active_manager_ip':
                        str(distributed_installation[2].private_ip_address)
                },
                'postgresql_client': {
                    'host':
                        str(distributed_installation[0].private_ip_address),
                    'postgres_password': 'postgres'
                },
                'services_to_install': MANAGER_SERVICES_TO_INSTALL
            })
            distributed_installation[4].additional_install_config.update({
                'sanity': SKIP_SANITY,
                'rabbitmq': {
                    'cluster_members': {
                        'localhost': {
                            'default': str(
                                distributed_installation[1].private_ip_address),
                        }
                    }
                },
                'cluster': {
                    'active_manager_ip':
                        str(distributed_installation[2].private_ip_address)
                },
                'postgresql_client': {
                    'host':
                        str(distributed_installation[0].private_ip_address),
                    'postgres_password': 'postgres'
                },
                'services_to_install': MANAGER_SERVICES_TO_INSTALL
            })
            if sanity:
                distributed_installation[5].additional_install_config.update({
                    'sanity': SKIP_SANITY
                })

    hosts = DistributedInstallationCloudifyManager(
        cfy=cfy,
        ssh_key=ssh_key,
        tmpdir=module_tmpdir,
        attributes=attributes,
        logger=logger,
        upload_plugins=False,
        cluster=cluster,
        sanity=sanity,
        template_inputs=template_inputs,
        tf_template=tf_template
    )

    hosts.preconfigure_callback = _preconfigure_callback_cluster

    all_hosts_list = hosts.instances
    try:
        hosts.create()
        # At this point, we have 3 managers in a cluster with 1 external
        # database and 1 external rabbitmq machine inside of hosts
        if cluster:
            hosts.instances = hosts.instances[2:]
        yield hosts
    finally:
        if cluster:
            hosts.instances = all_hosts_list
        hosts.destroy()


@pytest.fixture(scope='function')
def distributed_ha_hello_worlds(cfy, distributed_installation, attributes,
                                ssh_key, tmpdir, logger):
    # Pick a manager to operate on, and trust the cluster to work with us
    manager = distributed_installation.instances[0]

    hws = []
    for i in range(0, 2):
        tenant = prepare_and_get_test_tenant(
            'clusterhello{num}'.format(num=i),
            manager,
            cfy,
        )
        hw = centos_hello_world(
            cfy, manager, attributes, ssh_key, logger, tmpdir,
            tenant=tenant, suffix=str(i),
        )
        hws.append(hw)

    yield hws
    for hw in hws:
        if hw.cleanup_required:
            logger.info('Cleaning up hello world...')
            manager.use()
            hw.cleanup()


@pytest.fixture(scope='function')
def distributed_nodecellar(cfy, distributed_installation, attributes,
                           ssh_key, tmpdir, logger):
    manager = distributed_installation.manager
    manager.use()
    tenant = prepare_and_get_test_tenant(TENANT_NAME, manager, cfy)
    nc = NodeCellarExample(
        cfy, manager, attributes, ssh_key, logger, tmpdir,
        tenant=tenant, suffix='simple')
    nc.blueprint_file = 'simple-blueprint-with-secrets.yaml'
    yield nc