########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

from cosmo_tester.framework.examples import get_example_deployment

pre_bootstrap_state = None


def test_teardown(bootstrap_test_manager, ssh_key, logger, test_config):
    check_pre_bootstrap_state(bootstrap_test_manager)
    bootstrap_test_manager.bootstrap()

    bootstrapped_state = _get_system_state(bootstrap_test_manager)
    expected_diffs = {}

    example = get_example_deployment(bootstrap_test_manager,
                                     ssh_key, logger, 'teardown',
                                     test_config)
    example.upload_and_verify_install()
    example.uninstall()

    for key in 'os users', 'os groups':
        # Fetch the new users and groups created during the bootstrap
        expected_diffs[key] = (
            set(bootstrapped_state[key]) - set(pre_bootstrap_state[key]))
    expected_diffs['yum packages'] = {'cloudify-cli'}
    expected_diffs['folders in /opt'] = {'cfy'}

    bootstrap_test_manager.teardown()
    current_state = _get_system_state(bootstrap_test_manager)
    diffs = {}

    for key in current_state:
        pre_bootstrap_set = set(pre_bootstrap_state[key])
        current_set = set(current_state[key])

        diff = current_set - pre_bootstrap_set
        if diff:
            diffs[key] = diff

    assert diffs == expected_diffs


def check_pre_bootstrap_state(manager):
    global pre_bootstrap_state
    pre_bootstrap_state = _get_system_state(manager)

    # Some manual additions, as we know these files will be generated by the BS
    pre_bootstrap_state['yum packages'] += [
        'python-pip', 'libxslt', 'daemonize'
    ]
    pre_bootstrap_state['folders in /opt'] += [
        'python_NOTICE.txt',
        'lib',
        'cloudify-manager-install'
    ]
    pre_bootstrap_state['folders in /var/log'] += [
        'yum.log',
        'cloudify'
    ]
    pre_bootstrap_state['init_d service files (/etc/rc.d/init.d/)'] += [
        'jexec'
    ]


def _get_system_state(mgr):
    with mgr.ssh() as fabric:
        systemd = fabric.run('ls /usr/lib/systemd/system').stdout.split()
        init_d = fabric.run('ls /etc/rc.d/init.d/').stdout.split()
        sysconfig = fabric.run('ls /etc/sysconfig').stdout.split()
        opt_dirs = fabric.run('ls /opt').stdout.split()
        etc_dirs = fabric.run('ls /etc').stdout.split()
        var_log_dirs = _skip_system_logs(
            fabric.run('ls /var/log').stdout.split()
        )

        packages = fabric.run('rpm -qa').stdout.split()
        # Prettify the packages output
        packages = [package.rsplit('-', 2)[0] for package in packages]

        users = fabric.run('cut -d: -f1 /etc/passwd').stdout.split()
        groups = fabric.run('cut -d: -f1 /etc/group').stdout.split()
    return {
        'systemd service files (/usr/lib/systemd/system)': systemd,
        'init_d service files (/etc/rc.d/init.d/)': init_d,
        'service config files (/etc/sysconfig)': sysconfig,
        'folders in /opt': opt_dirs,
        'folders in /etc': etc_dirs,
        'folders in /var/log': var_log_dirs,
        'yum packages': packages,
        'os users': users,
        'os groups': groups,
    }


def _skip_system_logs(var_log_dirs):
    """Omit log dirs that are created by the system.

    We're not interested in directories from /var/log that were created
    by the OS (eg. snapshots of logs from the previous day created at midnight)

    Example OS log directories:
        btmp-20190812
        cron-20190812
        maillog-20190812
        messages-20190812
        secure-20190812
        spooler-20190812
    """
    os_logs = {'btmp', 'cron', 'maillog', 'messages', 'secure', 'spooler'}
    return [
        log_dir for log_dir in var_log_dirs
        if not any(log_dir.startswith(os_dir) for os_dir in os_logs)
    ]
