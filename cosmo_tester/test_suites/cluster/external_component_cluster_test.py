import os
import pytest

from cosmo_tester.test_suites.cluster import check_managers
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.test_suites.snapshots import (
    create_snapshot,
    restore_snapshot,
)
from .cfy_cluster_manager_shared import (
    _get_config_dict,
    _set_rpm_path,
    _install_cluster,
    _upgrade_cluster,
)


# This is to confirm that we work with a single DB endpoint set (e.g. on a
# PaaS).
# It is not intended that a single external DB be used in production.
@pytest.mark.six_vms
@pytest.mark.component
def test_cluster_single_db(cluster_with_single_db, logger, ssh_key,
                           test_config):
    broker1, broker2, broker3, db, mgr1, mgr2 = cluster_with_single_db

    example = get_example_deployment(mgr1, ssh_key, logger, 'cluster_1_db',
                                     test_config)
    example.inputs['server_ip'] = mgr1.ip_address
    example.upload_and_verify_install()

    logger.info('Creating snapshot')
    snapshot_id = 'cluster_test_snapshot'
    create_snapshot(mgr1, snapshot_id, logger)

    logger.info('Restoring snapshot')
    restore_snapshot(mgr2, snapshot_id, logger, force=True,
                     cert_path=mgr2.api_ca_path,
                     admin_password=mgr1.mgr_password)

    check_managers(mgr1, mgr2, example)


@pytest.mark.three_vms
@pytest.mark.upgrade
@pytest.mark.parametrize('base_version', ['6.3.2-ga', '6.4.1-ga'])
def test_upgrade_external_db(
        base_version, three_vms, logger, ssh_key, test_config):
    ext_db_fqdn = os.environ["EXTDB_FQDN"]
    ext_db_password = os.environ["EXTDB_PSWD"]

    nodes_list = [node for node in three_vms]
    mgr = nodes_list[0]

    _cleanup_external_db(ext_db_fqdn, ext_db_password, mgr)

    # download the ca-cert bundle for the external db
    mgr.run_command('curl https://truststore.pki.rds.amazonaws.com/'
                    'eu-west-1/eu-west-1-bundle.pem '
                    '-o /tmp/eu-west-1-bundle.pem')

    config_dict = _get_config_dict('3+ext_db', test_config, mgr.username)
    _set_rpm_path(config_dict, test_config, base_version)
    _update_3_nodes_ext_db_config_dict_vms(
        config_dict, nodes_list, ext_db_fqdn, ext_db_password)
    _install_cluster(mgr, three_vms, config_dict, test_config,
                     ssh_key, logger)
    _upgrade_cluster(nodes_list, mgr, test_config, logger)


def _cleanup_external_db(ext_db_fqdn, ext_db_password, node):
    cleanup_script = f'''
if PGPASSWORD={ext_db_password} psql -U postgres -h {ext_db_fqdn} -p 5432 \
   -c "\\l" | grep -q "cloudify"; then
   PGPASSWORD=cloudify psql -U cloudify postgres -h {ext_db_fqdn} -p 5432 \
   -c "drop database cloudify_db"
   PGPASSWORD=cloudify psql -U cloudify postgres -h {ext_db_fqdn} -p 5432 \
   -c "drop database stage"
   PGPASSWORD=cloudify psql -U cloudify postgres -h {ext_db_fqdn} -p 5432 \
   -c "drop database composer"
   PGPASSWORD={ext_db_password} psql -U postgres -h {ext_db_fqdn} -p 5432 \
   -c "drop user cloudify"
fi
    '''
    node.run_command('yum install -y postgresql', use_sudo=True)
    node.run_command(cleanup_script)
    node.run_command('yum remove  -y postgresql', use_sudo=True)


def _update_3_nodes_ext_db_config_dict_vms(
        config_dict, existing_vms_list, ext_db_fqdn, ext_db_password):
    for i, node in enumerate(existing_vms_list, start=1):
        config_dict['existing_vms']['node-{0}'.format(i)].update({
            'private_ip': str(node.private_ip_address),
            'public_ip': f'{node.private_ip_address}'
        })
        # Just put some FQDN, because when public_ip is an IP address,
        # the external certificate cannot be provided.
        # Public IPs are not used in this test.
    config_dict['external_db_configuration']['host'] = ext_db_fqdn
    config_dict['external_db_configuration']['ca_path'] = \
        '/tmp/eu-west-1-bundle.pem'
    config_dict['external_db_configuration']['server_password'] = \
        ext_db_password
