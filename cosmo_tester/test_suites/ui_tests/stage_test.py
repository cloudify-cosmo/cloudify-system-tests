import subprocess
import os


def test_stage(test_ui_manager, ssh_key, logger, test_config):
    logger.info('Installing dependencies to run system tests...')
    subprocess.call(['npm', 'run', 'beforebuild'],
                    cwd=test_config['ui']['stage_repo'])
    if test_config['ui']['update']:
        logger.info('Starting update of Stage package on Manager...')
        logger.info('Creating Stage package...')
        subprocess.call(['npm', 'run', 'build'],
                        cwd=test_config['ui']['stage_repo'])
        subprocess.call(['npm', 'run', 'zip'],
                        cwd=test_config['ui']['stage_repo'])

        logger.info('Uploading Stage package...')
        os.environ["MANAGER_USER"] = test_ui_manager.username
        os.environ["MANAGER_IP"] = test_ui_manager.ip_address
        os.environ["SSH_KEY_PATH"] = ssh_key.private_key_path
        subprocess.call(['npm', 'run', 'upload'],
                        cwd=test_config['ui']['stage_repo'])

    logger.info('Starting Stage system tests...')
    logger.info('Using test host at {0}'.format(
        os.environ["STAGE_E2E_SELENIUM_HOST"]))
    os.environ["STAGE_E2E_MANAGER_URL"] = test_ui_manager.ip_address
    subprocess.check_call(['npm', 'run', 'e2e'],
                          cwd=test_config['ui']['stage_repo'])
