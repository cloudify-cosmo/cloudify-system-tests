import retrying
import requests


def test_status(image_based_manager, logger):
    _check_status(image_based_manager, logger)

    logger.info('Stopping a manager service')
    image_based_manager.run_command(
        'sudo supervisorctl stop {svc} || sudo systemctl stop {svc}'.format(
            svc='cloudify-amqp-postgres',
        )
    )

    _check_status(image_based_manager, logger, healthy=False)

    image_based_manager.run_command(
        'sudo supervisorctl start {svc} || sudo systemctl start {svc}'.format(
            svc='cloudify-amqp-postgres',
        )
    )

    _check_status(image_based_manager, logger)


# Allow time for services to start when we restart them
@retrying.retry(stop_max_attempt_number=10, wait_fixed=1000)
def _check_status(manager, logger, healthy=True):
    if healthy:
        logger.info('Checking for healthy status')
        expected_status = 'OK'
        expected_return = 200
    else:
        logger.info('Checking for unhealthy status')
        expected_status = 'Fail'
        expected_return = 500

    status = manager.client.manager.get_status()
    logger.debug('Got status: %s', status)
    short_status = requests.get(
        'https://{}/api/v3.1/ok'.format(manager.ip_address),
        verify=manager.api_ca_path,
    )
    logger.debug('Got short status: %s', short_status)

    assert status.get('status') == expected_status
    assert short_status.text.strip() == '"{}"'.format(
        expected_status.upper())
    assert short_status.status_code == expected_return
