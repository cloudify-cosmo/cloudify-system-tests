def get_image_and_username(os, test_config):
    image = test_config.platform['{}_image'.format(os)]
    username = test_config['test_os_usernames'][os]
    return image, username
