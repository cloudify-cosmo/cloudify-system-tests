import os
import time

import pytest

from cloudify_rest_client.exceptions import CloudifyClientError
from cosmo_tester.framework.util import create_deployment, set_client_tenant

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


@pytest.fixture(scope='module')
def prepared_manager(image_based_manager, logger):
    tenants = sorted(TENANT_DEPLOYMENT_COUNTS.keys())

    for tenant in tenants:
        # Sometimes rabbit isn't ready to have new tenants added immediately
        # after startup, so wait for the tenants to be successfully created
        # before we continue (to avoid it erroring when creating a deployment
        # instead)
        for attempt in range(30):
            try:
                if tenant != 'default_tenant':
                    image_based_manager.client.tenants.create(tenant)
                    break
            except CloudifyClientError:
                time.sleep(2)

    deployment_ids = []
    for tenant in tenants:
        with set_client_tenant(image_based_manager.client, tenant):
            for blueprint, bp_path in BLUEPRINTS.items():
                image_based_manager.client.blueprints.upload(
                    path=bp_path,
                    entity_id=blueprint,
                )

            for bp_name, count in TENANT_DEPLOYMENT_COUNTS[tenant].items():
                for i in range(count):
                    deployment_id = bp_name + str(i)
                    create_deployment(
                        image_based_manager.client, bp_name, deployment_id,
                        logger,
                    )
                    deployment_ids.append(deployment_id)
                image_based_manager.wait_for_all_executions()
                for i in range(count):
                    deployment_id = bp_name + str(i)
                    image_based_manager.client.executions.start(
                        deployment_id,
                        'install',
                    )
                image_based_manager.wait_for_all_executions()

    _create_sites(image_based_manager, deployment_ids)
    yield image_based_manager
