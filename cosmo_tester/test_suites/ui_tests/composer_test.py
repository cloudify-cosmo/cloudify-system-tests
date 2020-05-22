import subprocess
import os


def test_composer(test_ui_manager, ssh_key, logger, test_config):
    logger.info('Installing dependencies to run system tests...')
    subprocess.call(['npm', 'ci'],
                    cwd=test_config['ui']['composer_repo'])
    if test_config['ui']['update']:
        logger.info('Starting update of Composer package on Manager...')
        logger.info('Creating Composer package...')
        subprocess.call(['bower', 'install'],
                        cwd=test_config['ui']['composer_repo'])
        subprocess.call(['grunt', 'pack'],
                        cwd=test_config['ui']['composer_repo'])

        logger.info('Uploading Composer package...')
        os.environ["MANAGER_USER"] = test_ui_manager.username
        os.environ["MANAGER_IP"] = test_ui_manager.ip_address
        os.environ["SSH_KEY_PATH"] = ssh_key.private_key_path
        subprocess.call(['npm', 'run', 'upload'],
                        cwd=test_config['ui']['composer_repo'])

    logger.info('Starting Composer system tests...')
    os.environ["COMPOSER_E2E_MANAGER_URL"] = test_ui_manager.ip_address
    subprocess.check_call(['npm', 'run', 'e2e'],
                          cwd=test_config['ui']['composer_repo'])
