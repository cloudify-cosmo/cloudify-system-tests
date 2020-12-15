import subprocess
import os


def test_composer(test_ui_manager, ssh_key, logger, test_config):
    os.environ["MANAGER_USER"] = test_ui_manager.username
    os.environ["MANAGER_IP"] = test_ui_manager.ip_address
    os.environ["SSH_KEY_PATH"] = ssh_key.private_key_path
    subprocess.check_call(['npm', 'run', 'e2e:ci'],
                    cwd=test_config['ui']['composer_repo'])
