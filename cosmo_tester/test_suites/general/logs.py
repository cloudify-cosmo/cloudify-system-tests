import time
import subprocess
from zipfile import ZipFile


def test_logs_aio(image_based_manager, tmpdir, logger):
    _test_logs([image_based_manager], tmpdir, logger)


def test_logs_cluster(three_nodes_cluster, tmpdir, logger):
    _test_logs(three_nodes_cluster, tmpdir, logger)


def _test_logs(managers, tmpdir, logger):
    manager_logs_tmp = '/tmp/logs'
    local_logs_base = tmpdir / 'extracted'
    dump_name = 'testbundle-{:.0f}'.format(time.time())

    create_log_bundle(managers, manager_logs_tmp, dump_name, logger)

    get_and_extract_log_bundle(managers[0], tmpdir, local_logs_base,
                               dump_name, logger)

    for manager in managers:
        compare_local_and_manager_logs(
            manager, local_logs_base, manager_logs_tmp, logger)


def create_log_bundle(managers, manager_logs_path, dump_name, logger):

    logger.info('Creating log dump')
    managers[0].client.log_bundles.create(dump_name)
    status = 'creating'
    while status == 'creating':
        status = managers[0].client.log_bundles.get(dump_name).get(
            'status', 'creating'
        )
    assert status == 'created'

    logger.info('Preparing manager logs comparison')
    for manager in managers:
        manager.run_command(
            f'sudo cp -r /var/log/cloudify {manager_logs_path}')
        manager.run_command(
            f'sudo chown $(whoami). -R {manager_logs_path}')


def get_and_extract_log_bundle(manager, tmpdir, extracted_path, dump_name,
                               logger):
    logger.info('Downloading and extracting log bundle')
    logs_path = str(tmpdir / 'logbundle.zip')
    manager.client.log_bundles.download(dump_name, logs_path)
    with ZipFile(logs_path, 'r') as zipf:
        zipf.extractall(extracted_path)


def compare_local_and_manager_logs(manager, local_logs_base,
                                   manager_logs_path, logger):
    logger.info('Checking no logs failed to retrieve')
    retrieval_log_path = str(
        local_logs_base / manager.private_ip_address
    ) + '.log'
    with open(retrieval_log_path) as retrieval_log_handle:
        retrieval_log = retrieval_log_handle.read().lower()
        assert 'fail' not in retrieval_log

    local_logs_path = str(
        local_logs_base / manager.private_ip_address
    )
    local_logs = subprocess.check_output(
        ['find', local_logs_path, '-type', 'f']).decode(
        'utf8').strip().split('\n')

    manager_logs = manager.run_command(
        f'find {manager_logs_path} -type f').stdout.strip().split('\n')
    local_prefix = len(local_logs_path)
    manager_prefix = len(manager_logs_path)
    local_logs = sorted([log[local_prefix:] for log in local_logs])
    manager_logs = sorted([log[manager_prefix:] for log in manager_logs])

    logger.info('Checking all manager logs were retrieved')
    assert local_logs == manager_logs

    logger.info('Checking log contents match')
    mismatches = []
    for sub_path in local_logs:
        local_log = local_logs_path + sub_path
        manager_log = manager_logs_path + sub_path

        with open(local_log, 'rb') as local_handle:
            local_data = local_handle.read()

        # More data may have been logged after we asked for the bundle, so we
        # will just truncate it to reach the same time point (ish)
        local_length = len(local_data)
        manager.run_command(
            f"truncate -s '<{local_length}' {manager_log}")

        # Strip both in case of extra newlines in the cat output
        local_data = local_data.decode('utf8').strip()
        manager_data = manager.run_command(
            f'cat {manager_log}', hide_stdout=True).stdout.strip()

        if local_data != manager_data:
            mismatches.append(sub_path)

    mismatches = ','.join(mismatches)
    assert not mismatches, (
        f'The following logs had differences: {mismatches}'
    )
