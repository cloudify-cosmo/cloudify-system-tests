def test_folder_permissions(image_based_manager):

    general_cfyuser_perms = '750 cfyuser adm'
    expected_permissions = {
        '/opt/manager': general_cfyuser_perms,
        '/opt/manager/resources': general_cfyuser_perms,
        '/opt/manager/snapshot_status': general_cfyuser_perms,
        '/opt/manager/scripts/load_permissions.py': general_cfyuser_perms,
        '/opt/manager/scripts/create_system_filters.py': general_cfyuser_perms,
        '/opt/mgmtworker/config': general_cfyuser_perms,
        '/opt/mgmtworker/work': general_cfyuser_perms,
        '/opt/mgmtworker/work': general_cfyuser_perms,
        '/opt/mgmtworker/env/plugins': general_cfyuser_perms,
        '/opt/mgmtworker/env/source_plugins': general_cfyuser_perms,
        '/var/log/cloudify/rest': general_cfyuser_perms,
        '/var/log/cloudify/rabbitmq': general_cfyuser_perms,
        '/var/log/cloudify/mgmtworker': general_cfyuser_perms,
        '/var/log/cloudify/amqp-postgres': general_cfyuser_perms,
        '/var/log/cloudify/execution-scheduler': general_cfyuser_perms,
        '/opt/cloudify/encryption/update-encryption-key': '550 root cfyuser',
    }

    for path in expected_permissions:
        output = image_based_manager.run_command(
            'stat -c "%a %U %G" {}'.format(path)).stdout
        assert expected_permissions[path] in output
