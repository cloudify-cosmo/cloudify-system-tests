import os
import time

from path import Path
import pytest

from cloudify_rest_client.exceptions import CloudifyClientError
from cosmo_tester.framework.logger import get_logger
from cosmo_tester.framework.test_hosts import Hosts
from cosmo_tester.framework.util import (
    create_deployment,
    set_client_tenant,
    SSHKey,
)

from . import DEPLOYMENTS_PER_SITE


SMALL_BLUEPRINT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(
            __file__), '..', '..', 'resources/blueprints/summary/small.yaml'))
MULTIVM_BLUEPRINT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        '..', '..', 'resources/blueprints/summary/multivm.yaml'))
RELATIONS_BLUEPRINT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        '..', '..', 'resources/blueprints/summary/withrelations.yaml'))
BLUEPRINTS = {
    'small': SMALL_BLUEPRINT_PATH,
    'multivm': MULTIVM_BLUEPRINT_PATH,
    'relations': RELATIONS_BLUEPRINT_PATH,
}
TENANT_DEPLOYMENT_COUNTS = {
    'default_tenant': {
        'small': 2,
        'multivm': 1,
        'relations': 3,
    },
    'test1': {
        'small': 1,
        'multivm': 3,
        'relations': 2,
    },
    'test2': {
        'small': 3,
        'multivm': 2,
        'relations': 1,
    },
}


def _create_sites(manager, deployment_ids):
    for site_dep_count in DEPLOYMENTS_PER_SITE:
        site_name = site_dep_count['site_name']
        manager.client.sites.create(site_name)
        for i in range(site_dep_count['deployments']):
            manager.client.deployments.set_site(deployment_ids[i],
                                                site_name)
            deployment_ids.remove(deployment_ids[i])


@pytest.fixture(scope='session')
def session_tmpdir(request, tmpdir_factory, session_logger):
    suffix = 'summary_tests'
    temp_dir = Path(tmpdir_factory.mktemp(suffix))
    session_logger.info('Created temp folder: %s', temp_dir)

    return temp_dir


@pytest.fixture(scope='session')
def session_ssh_key(session_tmpdir, session_logger):
    key = SSHKey(session_tmpdir, session_logger)
    key.create()
    return key


@pytest.fixture(scope='session')
def session_logger(request):
    return get_logger('summary_tests')


@pytest.fixture(scope='session')
def prepared_manager(request, session_ssh_key, session_tmpdir, test_config,
                     session_logger):
    tenants = sorted(TENANT_DEPLOYMENT_COUNTS.keys())

    hosts = Hosts(
        session_ssh_key, session_tmpdir, test_config, session_logger, request)
    try:
        hosts.create()
        manager = hosts.instances[0]
        for tenant in tenants:
            # Sometimes rabbit isn't ready to have new tenants added
            # immediately after startup, so wait for the tenants to be
            # successfully created before we continue (to avoid it erroring
            # when creating a deployment instead)
            for attempt in range(30):
                try:
                    if tenant != 'default_tenant':
                        manager.client.tenants.create(tenant)
                        break
                except CloudifyClientError:
                    time.sleep(2)

        deployment_ids = []
        for tenant in tenants:
            with set_client_tenant(manager.client, tenant):
                for blueprint, bp_path in BLUEPRINTS.items():
                    manager.client.blueprints.upload(
                        path=bp_path,
                        entity_id=blueprint,
                    )

                for bp_name, count in TENANT_DEPLOYMENT_COUNTS[tenant].items():
                    for i in range(count):
                        deployment_id = bp_name + str(i)
                        create_deployment(
                            manager.client, bp_name, deployment_id,
                            session_logger,
                        )
                        deployment_ids.append(deployment_id)
                    manager.wait_for_all_executions()
                    for i in range(count):
                        deployment_id = bp_name + str(i)
                        manager.client.executions.start(
                            deployment_id,
                            'install',
                        )
                    manager.wait_for_all_executions()

        _create_sites(manager, deployment_ids)
        yield manager
    finally:
        hosts.destroy()
