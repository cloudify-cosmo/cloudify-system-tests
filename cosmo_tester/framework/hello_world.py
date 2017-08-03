import subprocess

import retrying

# CFY-6912
from cloudify_cli.commands.executions import (
    _get_deployment_environment_creation_execution,
    )

from .util import get_test_tenants, set_client_tenant, get_deployments_list

HELLO_WORLD_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example/archive/4.0.zip'  # noqa
# We need this because 3.4 (and 4.0!) snapshots don't handle agent_config,
# but 3.4 example blueprints use it instead of cloudify_agent
OLD_WORLD_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example/archive/3.3.1.zip' # noqa
BASE_ID = 'helloworld'
BLUEPRINT_ID = '{base}_bp'.format(base=BASE_ID)
DEPLOYMENT_ID = '{base}_dep'.format(base=BASE_ID)


def upload_and_install_helloworld(attributes, logger, manager, target_vm,
                                  tmpdir, prefix='', tenant=None,
                                  agent_user=None):
    if agent_user is None:
        agent_user = attributes['centos_7_username']

    assert not is_hello_world(target_vm), (
        'Hello world blueprint already installed!'
    )
    version = manager.branch_name
    message = 'Uploading helloworld blueprint to {version} manager'.format(
        version=version,
    )
    if tenant:
        message += ' for {tenant}'.format(tenant=tenant)
    logger.info(message)
    blueprint_id = prefix + BLUEPRINT_ID
    deployment_id = prefix + DEPLOYMENT_ID
    inputs = {
        'server_ip': target_vm.ip_address,
        'agent_user': agent_user,
        'agent_private_key_path': manager.remote_private_key_path,
    }
    upload_helloworld(
        manager,
        'singlehost-blueprint.yaml',
        blueprint_id,
        tenant,
        logger,
    )

    deploy_helloworld(
        manager,
        inputs,
        blueprint_id,
        deployment_id,
        tenant,
        logger,
    )

    with set_client_tenant(manager, tenant):
        execution = manager.client.executions.start(
            deployment_id,
            'install',
            )
    logger.info('Waiting for installation to finish')
    wait_for_execution(
        manager,
        execution,
        logger,
        tenant,
    )
    assert is_hello_world(target_vm), (
        'Hello world blueprint did not install correctly.'
    )


def upload_helloworld(manager, blueprint, blueprint_id, tenant, logger):
    version = manager.branch_name
    url = OLD_WORLD_URL if version in ('3.4.2', '4.0') else HELLO_WORLD_URL
    logger.info(
        'Uploading blueprint {blueprint} from archive {archive} as {name} '
        'for manager version {version}'.format(
            blueprint=blueprint,
            archive=url,
            name=blueprint_id,
            version=version,
        )
    )
    with set_client_tenant(manager, tenant):
        manager.client.blueprints.publish_archive(
            url,
            blueprint_id,
            blueprint,
        )


def deploy_helloworld(manager, inputs, blueprint_id,
                      deployment_id, tenant, logger):
    version = manager.branch_name
    message = 'Deploying {deployment} on {version} manager'.format(
        deployment=deployment_id,
        version=version,
    )
    if tenant:
        message += ' for {tenant}'.format(tenant=tenant)
    logger.info(message)
    with set_client_tenant(manager, tenant):
        manager.client.deployments.create(
            blueprint_id,
            deployment_id,
            inputs,
        )

        creation_execution = _get_deployment_environment_creation_execution(
            manager.client, deployment_id)
    logger.info('Waiting for execution environment')
    wait_for_execution(
        manager,
        creation_execution,
        logger,
        tenant,
    )
    logger.info('Deployment environment created')


def remove_and_check_deployments(hello_vms, manager, logger,
                                 tenants=None,
                                 with_prefixes=False):
    if tenants is None:
        tenants = get_test_tenants()
    for tenant in tenants:
        logger.info(
            'Uninstalling hello world deployments from manager for '
            '{tenant}'.format(
                tenant=tenant,
            )
        )
        logger.info('Found deployments: {deployments}'.format(
            deployments=', '.join(get_deployments_list(manager, tenant)),
        ))
        with set_client_tenant(manager, tenant):
            if with_prefixes:
                deployment_id = tenant + DEPLOYMENT_ID
            else:
                deployment_id = DEPLOYMENT_ID
            execution = manager.client.executions.start(
                deployment_id,
                'uninstall',
            )

        logger.info('Waiting for uninstall to finish')
        wait_for_execution(
            manager,
            execution,
            logger,
            tenant,
        )
        logger.info('Uninstalled deployments for {tenant}'.format(
            tenant=tenant,
        ))

    assert_hello_worlds(hello_vms, installed=False, logger=logger)


class ExecutionWaiting(Exception):
    """
    raised by `wait_for_execution` if it should be retried
    """
    pass


class ExecutionFailed(Exception):
    """
    raised by `wait_for_execution` if a bad state is reached
    """
    pass


def retry_if_not_failed(exception):
    return not isinstance(exception, ExecutionFailed)


@retrying.retry(
    stop_max_delay=5 * 60 * 1000,
    wait_fixed=10000,
    retry_on_exception=retry_if_not_failed,
)
def wait_for_execution(manager, execution, logger, tenant=None):
    base_message = 'Getting workflow execution [id={execution}]'.format(
        execution=execution['id'],
    )
    if tenant:
        logger.info(
            base_message + ' for tenant {tenant}'.format(
                tenant=tenant,
            )
        )
    else:
        logger.info(base_message)
    with set_client_tenant(manager, tenant):
        execution = manager.client.executions.get(execution['id'])
    logger.info('- execution.status = %s', execution.status)
    if execution.status not in execution.END_STATES:
        raise ExecutionWaiting(execution.status)
    if execution.status != execution.TERMINATED:
        raise ExecutionFailed(execution.status)
    return execution


def is_hello_world(vm):
    result = subprocess.check_output(
        'curl {ip}:8080 || echo "Curl failed."'.format(ip=vm.ip_address),
        shell=True,
    )
    return 'Cloudify Hello World' in result


def assert_hello_worlds(hello_vms, installed, logger):
    if installed:
        state = 'running'
    else:
        state = 'not running'
    logger.info('Confirming that hello world services are {state}.'.format(
        state=state,
    ))
    for hello_vm in hello_vms:
        if installed:
            assert is_hello_world(hello_vm), (
                'Hello world was not running after restore.'
            )
        else:
            assert not is_hello_world(hello_vm), (
                'Hello world blueprint did not uninstall correctly.'
            )
    logger.info('Hello world services are in expected state.')


