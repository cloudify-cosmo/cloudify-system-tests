import subprocess
import os


def test_composer(test_ui_manager, ssh_key, logger, test_config):
    logger.info('Installing dependencies to run system tests...')
    subprocess.call(['npm', 'run', 'beforebuild'],
                    cwd=test_config['ui']['composer_repo'])

    logger.info('Starting update of Composer package on Manager...')
    logger.info('Creating Composer package...')
    subprocess.call(['npm', 'run', 'build:coverage'],
                    cwd=test_config['ui']['composer_repo'])
    subprocess.call(['npm', 'run', 'zip'],
                    cwd=test_config['ui']['composer_repo'])
    logger.info('Uploading Composer package...')
    os.environ["MANAGER_USER"] = test_ui_manager.username
    os.environ["MANAGER_IP"] = test_ui_manager.ip_address
    os.environ["SSH_KEY_PATH"] = ssh_key.private_key_path
    subprocess.call(['npm', 'run', 'upload'],
                    cwd=test_config['ui']['composer_repo'])

    logger.info('Starting Composer system tests...')
    os.environ["COMPOSER_E2E_MANAGER_URL"] = test_ui_manager.ip_address

    e2e_pass = True
    try:
        subprocess.check_call(['npm', 'run', 'e2e'],
                              cwd=test_config['ui']['composer_repo'])
    except Exception:
        e2e_pass = False

    logger.info('Starting Composer unit tests...')
    subprocess.check_call(
                        'export NODE_OPTIONS="--max-old-space-size=8192"; ' +
                        'npm run test:frontend:coverage',
                        cwd=test_config['ui']['composer_repo'], shell=True)

    logger.info('Checking coverage...')
    subprocess.check_call(['npm', 'run', 'coverageCheck'],
                          cwd=test_config['ui']['composer_repo'])

    if not e2e_pass:
        logger.error('Composer system tests failed')
        raise Exception
