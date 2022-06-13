import binascii

from cosmo_tester.framework.util import get_resource_path

ICON_HASH = '25a5e3797302086d05851cdeee602dc5'


def add_stage_blueprint_icon(manager, blueprint_name, logger):
    if not stage_blueprint_icon_supported(manager):
        raise RuntimeError(
            "Can't add stage blueprint icon to manager of type "
            f"{manager.image_type}."
        )

    logger.info(
        'Injecting icon into stage for blueprints called %s',
        blueprint_name)

    icon_path = get_resource_path('icon.png')
    with open(icon_path, 'rb') as icon_handle:
        icon = icon_handle.read()

    icon_data = b'\\x' + binascii.hexlify(icon)
    icon_data = icon_data.decode('utf8')

    manager.run_command(
        "cfy_manager dbs shell -d stage 'INSERT INTO \"BlueprintAdditions\" "
        "(\"blueprintId\", image, \"createdAt\", \"updatedAt\") "
        f"VALUES ('\"'\"'{blueprint_name}'\"'\"', '\"'\"'{icon_data}"
        "'\"'\"', '\"'\"'2022-06-09 11:09:47.972+00'\"'\"', "
        "'\"'\"'2022-06-09 11:09:47.977+00'\"'\"');'"
    )


def stage_blueprint_icon_supported(manager):
    if manager.image_type.startswith('5'):
        if manager.image_type == '5.1.0':
            # This predates the cfy_manager dbs shell, and it's not worth
            # complicating the add script for the oldest version we support.
            return False
        return True
    if manager.image_type.startswith('6'):
        # Stage icons stopped existing in 6.4
        minor = manager.image_type.split('.')[1]
        if int(minor) < 4:
            return True
    return False


def check_icon(manager, tenant, blueprint, logger, exists=True):
    path = f'/opt/manager/resources/blueprints/{tenant}/{blueprint}/icon.png'
    result = manager.run_command(f'sudo md5sum {path} 2>&1 || true').stdout
    if exists:
        logger.info(
            'Checking icon is correct for %s in %s', blueprint, tenant)
        assert result.startswith(ICON_HASH)
    else:
        logger.info('Checking icon is absent for %s in %s', blueprint, tenant)
        assert ICON_HASH not in result
        assert 'No such' in result
