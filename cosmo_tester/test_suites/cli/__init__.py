import json
import time


def get_image_and_username(os, test_config):
    image = test_config.platform['{}_image'.format(os)]
    username = test_config['test_os_usernames'][os]
    return image, username


def _prepare(run, example, paths, logger):
    logger.info('Using manager')
    run(
        '{cfy} profiles use {ip} -u admin -p admin -t {tenant}'.format(
            cfy=paths['cfy'],
            ip=example.manager.private_ip_address,
            tenant=example.tenant,
        )
    )

    logger.info('Creating secret')
    run('{cfy} secrets create --secret-file {ssh_key} ssh_public_key'
        .format(**paths))


def _test_upload_and_install(run, example, paths, logger):
    logger.info('Uploading blueprint')
    run('{cfy} blueprints upload -b test_bp {blueprint}'.format(**paths))

    logger.info('Creating deployment')
    run('{cfy} deployments create -b test_bp -i {inputs_path} test_dep '
        .format(**paths))

    logger.info('Executing install workflow')
    run('{cfy} executions start install -d test_dep'.format(**paths))

    example.check_files()


def _test_cfy_install(run, example, paths, logger):
    logger.info('Running cfy install for blueprint')
    run(
        '{cfy} install --blueprint-id {blueprint} '
        '--deployment-id {deployment} --inputs {inputs_path} '
        '{blueprint_path}'.format(
            cfy=paths['cfy'],
            blueprint=example.blueprint_id,
            deployment=example.deployment_id,
            inputs_path=paths['inputs'],
            blueprint_path=paths['blueprint'],
        )
    )

    example.check_files()


def _test_teardown(run, example, paths, logger):
    logger.info('Starting uninstall workflow')
    run('{cfy} executions start uninstall -d test_dep'.format(**paths))

    example.check_all_test_files_deleted()

    logger.info('Deleting deployment')
    run('{cfy} deployments delete test_dep'.format(**paths))
    # With a sleep because this returns before the DB is updated
    time.sleep(4)

    logger.info('Checking deployment has been deleted.')
    deployments = json.loads(
        run('{cfy} deployments list --json'.format(**paths)).stdout
    )
    assert len(deployments) == 0

    logger.info('Deleting secret')
    run('{cfy} secrets delete ssh_public_key'.format(**paths))

    logger.info('Checking secret has been deleted.')
    secrets = json.loads(
        run('{cfy} secrets list --json'.format(**paths)).stdout
    )
    assert len(secrets) == 0

    logger.info('Deleting blueprint')
    run('{cfy} blueprints delete test_bp'.format(**paths))
    # With a sleep because this returns before the DB is updated
    time.sleep(4)

    logger.info('Checking blueprint has been deleted.')
    blueprints = json.loads(
        run('{cfy} blueprints list --json'.format(**paths)).stdout
    )
    assert len(blueprints) == 0
