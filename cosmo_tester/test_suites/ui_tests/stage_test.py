import subprocess
import os


def test_stage(test_ui_manager, ssh_key, logger, test_config):
    logger.info('Installing dependencies to run system tests...')
    subprocess.call(['npm', 'run', 'beforebuild'],
                    cwd=test_config['ui']['stage_repo'])

    logger.info('Starting update of Stage package on Manager...')
    logger.info('Creating Stage package...')
    subprocess.call(['npm', 'run', 'build:coverage'],
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
    os.environ["STAGE_E2E_MANAGER_URL"] = test_ui_manager.ip_address
    e2ePass = True
    try:
        subprocess.check_call(['npm', 'run', 'e2e'],
                          cwd=test_config['ui']['stage_repo'])
    except:
        e2ePass = False

    logger.info('Starting Stage unit tests...')
    subprocess.check_call(['npm', 'run', 'jest:coverage'],
                          cwd=test_config['ui']['stage_repo'])

    logger.info('Checking coverage...')
    subprocess.check_call(['npm', 'run', 'coverageCheck'],
                          cwd=test_config['ui']['stage_repo'])

    if not e2ePass:
        logger.error('Stage system tests failed')
        raise Exception
