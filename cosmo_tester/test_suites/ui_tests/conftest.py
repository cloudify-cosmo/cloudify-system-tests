import os
import subprocess

import pytest

from cosmo_tester.framework.test_hosts import Hosts


class MissingRepoError(Exception):
    pass


@pytest.fixture()
def test_ui_manager(test_config, ssh_key, module_tmpdir, logger,
                    request):
    repos_present = True
    for repo in ['stage', 'composer']:
        if not test_config['ui']['{}_repo'.format(repo)]:
            logger.error('ui.%s_repo path not set in test config', repo)
            repos_present = False
        elif not os.path.isdir(test_config['ui']['{}_repo'.format(repo)]):
            logger.error('ui.%srepo target path is not a dir in test config.'
                         'Path was set to %s',
                         repo, test_config['ui']['{}_repo'.format(repo)])
            repos_present = False

    if not repos_present:
        raise MissingRepoError(
            'To run UI tests the composer_repo and stage_repo test '
            'config entries must be pointing to local clones of the '
            'stage and composer repositories.'
        )

    try:
        subprocess.check_call(['npm', 'ci', '--help'])
    except Exception:
        logger.error('npm supporting ci must be installed to run ui tests.')
        raise

    hosts = Hosts(
        ssh_key, module_tmpdir, test_config, logger, request)
    try:
        hosts.create()
        hosts.instances[0].restservice_expected = True
        hosts.instances[0].finalize_preparation()
        hosts.instances[0].use()
        yield hosts.instances[0]
    finally:
        hosts.destroy()
