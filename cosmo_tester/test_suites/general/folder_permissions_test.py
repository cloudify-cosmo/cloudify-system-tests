def test_folder_permissions(image_based_manager, logger):
    mode, user, group = _get_path_permissions(image_based_manager,
                                              '/opt/manager',
                                              logger)

    assert user == 'cfyuser'
    assert group == 'cfyuser'
    # We require that /opt/manager not be world-accessible
    _check_file_mode(mode, expected_other_perms='0')


def _get_path_permissions(manager, path, logger):
    perms = manager.run_command('stat -c "%a %U %G" {}'.format(path)).stdout

    # The result should be something like "750 cfyuser cfyuser\n"
    perms = perms.strip()
    mode, user, group = perms.split()
    logger.info('Path %s has mode %s, user %s, group %s',
                path, mode, user, group)
    return mode, user, group


def _check_file_mode(mode,
                     expected_owner_perms=None,
                     expected_group_perms=None,
                     expected_other_perms=None):
    assert len(mode) == 3, "File mode should have a length of 3"
    owner, group, other = mode
    if expected_owner_perms:
        assert expected_owner_perms == owner
    if expected_group_perms:
        assert expected_group_perms == group
    if expected_other_perms:
        assert expected_other_perms == other
