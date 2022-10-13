def check_manager_using_correct_idp(manager, logger, expected):
    logger.info('Confirming %s IDP is being used on %s.',
                expected, manager.ip_address)
    assert manager.client.idp.get() == expected


def delete_a_user(user, groups, client, logger):
    logger.info('Checking user exists before deletion')
    assert user in _get_manager_users(client)
    logger.info('Removing user from groups')
    for group in groups:
        client.user_groups.remove_user(user, group)
    logger.info('Deleting user and confirming deletion')
    client.users.delete(user)
    assert user not in _get_manager_users(client)


def _get_manager_users(client):
    return [item['username']
            for item in client.users.list(_include=['username'])]
