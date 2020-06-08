from contextlib import contextmanager
from datetime import datetime, timedelta
import errno
import glob
import json
import logging
import os
import requests
import retrying
import shlex
import socket
import subprocess
import sys
from tempfile import mkstemp
import time
import yaml

from cloudify_rest_client import CloudifyClient
from cloudify_rest_client.exceptions import CloudifyClientError

import cosmo_tester
from cosmo_tester import resources
from cosmo_tester.framework.constants import CLOUDIFY_TENANT_HEADER
from cosmo_tester.framework.exceptions import ProcessExecutionError


def pass_stdout(line, input_queue, process):
    output = line.encode(process.call_args['encoding'], 'replace')
    process._stdout.append(output)
    sys.stdout.write(output)


def pass_stderr(line, input_queue, process):
    output = line.encode(process.call_args['encoding'])
    process._stderr.append(output)
    sys.stderr.write(output)


def get_resource_path(resource, resources_dir=None):
    resources_dir = resources_dir or os.path.dirname(resources.__file__)
    return os.path.join(resources_dir, resource)


def create_rest_client(
        manager_ip,
        username=None,
        password=None,
        tenant=None,
        **kwargs):
    return CloudifyClient(
        host=manager_ip,
        username=username or 'admin',
        password=password or 'admin',
        tenant=tenant or 'default_tenant',
        **kwargs)


def test_cli_package_url(url):
    error_base = (
        # Trailing space for better readability when cause of error
        # is appended if there are problems.
        '{url} does not appear to be a valid package URL. '
    ).format(url=url)
    try:
        verification = requests.head(url, allow_redirects=True)
    except requests.exceptions.RequestException as err:
        raise RuntimeError(
            error_base +
            'Attempting to retrieve URL caused error: {exc}'.format(
                exc=str(err),
            )
        )
    if verification.status_code != 200:
        raise RuntimeError(
            error_base +
            'Response to HEAD request was {status}'.format(
                status=verification.status_code,
            )
        )


def get_cli_package_url(platform, test_config):
    # Override URLs if they are provided in the config
    config_cli_urls = test_config['cli_urls_override']

    if config_cli_urls.get(platform):
        url = config_cli_urls[platform]
    else:
        if test_config['premium']:
            filename = 'cli-premium-packages.yaml'
            packages_key = 'cli_premium_packages_urls'
        else:
            filename = 'cli-packages.yaml'
            packages_key = 'cli_packages_urls'
        url = yaml.load(_get_package_url(filename, test_config))[
            packages_key][platform]

    test_cli_package_url(url)

    return url


def _get_package_url(filename, test_config):
    """Gets the package URL(s) from the local premium or versions repo.
    See the package_urls section of the test config for details.
    """
    package_urls_key = 'premium' if test_config['premium'] else 'community'

    package_url_file = os.path.abspath(
        os.path.join(
            os.path.dirname(cosmo_tester.__file__), '..',
            test_config['package_urls'][package_urls_key],
            'packages-urls', filename,
        )
    )

    with open(package_url_file) as package_url_handle:
        return package_url_handle.read()


@retrying.retry(stop_max_attempt_number=20, wait_fixed=5000)
def assert_snapshot_created(manager, snapshot_id):
    snapshots = manager.client.snapshots.list()

    existing_snapshots = {
        snapshot['id']: snapshot['status']
        for snapshot in snapshots
    }

    assert snapshot_id in existing_snapshots.keys(), (
        'Snapshot {snapshot} does not appear to exist. Snapshots found were: '
        '{snapshots}'.format(
            snapshot=snapshot_id,
            snapshots=', '.join(existing_snapshots.keys()),
        )
    )

    assert existing_snapshots[snapshot_id] == 'created', (
        'Snapshot {snapshot} is not yet created. it is currently: '
        '{state}'.format(
            snapshot=snapshot_id,
            state=existing_snapshots[snapshot_id],
        )
    )


@contextmanager
def set_client_tenant(client, tenant):
    if tenant:
        original = client._client.headers[CLOUDIFY_TENANT_HEADER]

        client._client.headers[CLOUDIFY_TENANT_HEADER] = tenant

    try:
        yield
    except Exception:
        raise
    finally:
        if tenant:
            client._client.headers[CLOUDIFY_TENANT_HEADER] = original


def prepare_and_get_test_tenant(test_param, manager, test_config):
    """
        Prepares a tenant for testing based on the test name (or other
        identifier passed in as 'test_param'), and returns the name of the
        tenant that should be used for this test.
    """
    if test_config['premium']:
        tenant = test_param
        try:
            manager.client.tenants.create(tenant)
        except CloudifyClientError as err:
            if 'already exists' in str(err):
                pass
            else:
                raise
    else:
        tenant = 'default_tenant'
        # It is expected that the plugin is already uploaded for the
        # default tenant
    return tenant


def mkdirs(folder_path):
    try:
        os.makedirs(folder_path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(folder_path):
            pass
        else:
            raise


def run(command, retries=0, stdin=b'', ignore_failures=False,
        globx=False, shell=False, env=None, stdout=None, logger=logging):
    def subprocess_preexec():
        cfy_umask = 0o22
        os.umask(cfy_umask)
    if isinstance(command, str) and not shell:
        command = shlex.split(command)
    stderr = subprocess.PIPE
    stdout = stdout or subprocess.PIPE
    if globx:
        glob_command = []
        for arg in command:
            glob_command.append(glob.glob(arg))
        command = glob_command
    logger.debug('Running: {0}'.format(command))
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout,
                            stderr=stderr, shell=shell, env=env,
                            preexec_fn=subprocess_preexec)
    proc.aggr_stdout, proc.aggr_stderr = proc.communicate(input=stdin)
    if proc.returncode != 0:
        command_str = ' '.join(command)
        if retries:
            logger.warn('Failed running command: {0}. Retrying. '
                        '({1} left)'.format(command_str, retries))
            proc = run(command, retries - 1)
        elif not ignore_failures:
            msg = 'Failed running command: {0} ({1}).'.format(
                command_str, proc.aggr_stderr)
            raise ProcessExecutionError(msg, proc.returncode)
    return proc


def write_to_tempfile(contents, json_dump=False):
    fd, file_path = mkstemp()
    os.close(fd)
    if json_dump:
        contents = json.dumps(contents)

    with open(file_path, 'w') as f:
        f.write(contents)

    return file_path


CSR_CONFIG_TEMPLATE = """
[req]
distinguished_name = req_distinguished_name
req_extensions = server_req_extensions
[ server_req_extensions ]
subjectAltName={metadata}
[ req_distinguished_name ]
commonName = _common_name # ignored, _default is used instead
commonName_default = {cn}
"""


@contextmanager
def _csr_config(cn, metadata=None, logger=logging):
    """Prepare a config file for creating a ssl CSR.

    :param cn: the subject commonName
    :param metadata: string to use as the subjectAltName, should be formatted
                     like "IP:1.2.3.4,DNS:www.com"
    """
    logger.debug('Creating csr-config file with:\nCN:{0}\nMetaData:{1}'.format(
        cn, metadata
    ))
    csr_config = CSR_CONFIG_TEMPLATE.format(cn=cn, metadata=metadata)
    temp_config_path = write_to_tempfile(csr_config)

    yield temp_config_path


def _format_ips(ips):
    altnames = set(ips)

    # Ensure we trust localhost
    altnames.add('127.0.0.1')
    altnames.add('localhost')

    subject_altdns = [
        'DNS:{name}'.format(name=name)
        for name in altnames
    ]
    subject_altips = []
    for name in altnames:
        ip_address = False
        try:
            socket.inet_pton(socket.AF_INET, name)
            ip_address = True
        except socket.error:
            # Not IPv4
            pass
        try:
            socket.inet_pton(socket.AF_INET6, name)
            ip_address = True
        except socket.error:
            # Not IPv6
            pass
        if ip_address:
            subject_altips.append('IP:{name}'.format(name=name))

    cert_metadata = ','.join([
        ','.join(subject_altdns),
        ','.join(subject_altips),
    ])
    return cert_metadata


def generate_ssl_certificate(ips,
                             cn,
                             cert_path,
                             key_path,
                             sign_cert=None,
                             sign_key=None,
                             sign_key_password=None,
                             logger=logging):
    """Generate a public SSL certificate and a private SSL key

    :param ips: the ips (or names) to be used for subjectAltNames
    :type ips: List[str]
    :param cn: the subject commonName for the new certificate
    :type cn: str
    :param cert_path: path to save the new certificate to
    :type cert_path: str
    :param key_path: path to save the key for the new certificate to
    :type key_path: str
    :param sign_cert: path to the signing cert (self-signed by default)
    :type sign_cert: str
    :param sign_key: path to the signing cert's key (self-signed by default)
    :type sign_key: str
    :return: The path to the cert and key files on the manager
    """
    # Remove duplicates from ips
    subject_altnames = _format_ips(ips)
    logger.debug(
        'Generating SSL certificate {0} and key {1} with subjectAltNames: {2}'
        .format(cert_path, key_path, subject_altnames)
    )

    csr_path = '{0}.csr'.format(cert_path)

    with _csr_config(cn, subject_altnames) as conf_path:
        run([
            'openssl', 'req',
            '-newkey', 'rsa:2048',
            '-nodes',
            '-batch',
            '-sha256',
            '-config', conf_path,
            '-out', csr_path,
            '-keyout', key_path,
        ])
        x509_command = [
            'openssl', 'x509',
            '-days', '3650',
            '-sha256',
            '-req', '-in', csr_path,
            '-out', cert_path,
            '-extensions', 'server_req_extensions',
            '-extfile', conf_path
        ]

        if sign_cert and sign_key:
            x509_command += [
                '-CA', sign_cert,
                '-CAkey', sign_key,
                '-CAcreateserial'
            ]
            if sign_key_password:
                x509_command += [
                    '-passin', 'pass:{0}'.format(sign_key_password)
                ]
        else:
            x509_command += [
                '-signkey', key_path
            ]
        run(x509_command)

    logger.debug('Generated SSL certificate: {0} and key: {1}'.format(
        cert_path, key_path
    ))
    return cert_path, key_path


def generate_ca_cert(ca_cert_path, ca_key_path):
    run([
        'openssl', 'req',
        '-x509',
        '-nodes',
        '-newkey', 'rsa:2048',
        '-days', '3650',
        '-batch',
        '-out', ca_cert_path,
        '-keyout', ca_key_path
    ])


class ExecutionTimeout(Exception):
    """Execution timed out."""


class ExecutionFailed(Exception):
    """Execution failed."""


def wait_for_execution(client, execution, logger, tenant=None, timeout=5*60,
                       allow_client_error=False):
    logger.info(
        'Getting workflow execution [id={execution}]'.format(
            execution=execution['id'],
        )
    )
    current_time = datetime.now()
    timeout_time = current_time + timedelta(seconds=timeout)
    output_events(client, execution, logger, to_time=current_time)

    with set_client_tenant(client, tenant):
        while True:
            prev_time = current_time
            current_time = datetime.now()

            try:
                execution = client.executions.get(execution['id'])

                output_events(client, execution, logger, prev_time,
                              current_time)
            except CloudifyClientError as err:
                if allow_client_error:
                    logger.warn(
                        'Error trying to get execution state, retrying: %s',
                        err
                    )
                    if current_time >= timeout_time:
                        raise
                    time.sleep(2)
                    continue
                else:
                    raise

            if current_time >= timeout_time:
                raise ExecutionTimeout(
                    'Execution {exc_id} timed out in state: {status}'.format(
                        exc_id=execution['id'],
                        status=execution.status,
                    )
                )

            if execution.status in execution.END_STATES:
                # Give time for any last second events
                time.sleep(2)
                output_events(client, execution, logger, current_time)

                if execution.status != execution.TERMINATED:
                    logger.warning('Execution failed')
                    raise ExecutionFailed(
                        '{status}: {error}'.format(
                            status=execution.status,
                            error=execution['error'],
                        )
                    )

                logger.info('Execution completed in state {status}'.format(
                        status=execution.status,
                    )
                )
                break

    return execution


def run_blocking_execution(client, deployment_id, workflow_id, logger,
                           params=None, tenant=None, timeout=(15*60)):
    with set_client_tenant(client, tenant):
        execution = client.executions.start(
            deployment_id, workflow_id, parameters=params,
        )
    wait_for_execution(client, execution, logger,
                       tenant=tenant, timeout=timeout)


def output_events(client, execution, logger, from_time=None, to_time=None):
    if from_time:
        from_time = from_time.strftime('%Y-%m-%d %H:%M:%S')
    if to_time:
        to_time = to_time.strftime('%Y-%m-%d %H:%M:%S')
    events = client.events.list(
        execution_id=execution.id,
        _size=1000,
        include_logs=True,
        sort='reported_timestamp',
        from_datetime=from_time,
        to_datetime=to_time,
    )
    log_methods = {
        'debug': logger.debug,
        'info': logger.info,
        'warn': logger.warn,
        'warning': logger.warn,
        'error': logger.error,
    }
    for event in events:
        if event.get('type') == 'cloudify_event':
            level = 'info'
        else:
            level = event.get('level')

        if level not in log_methods:
            logger.warn('Unknown event level %s.', level)
            logger.warn('Event was: %s', event)
        else:
            message = event.get('message', '<MESSSAGE NOT FOUND>')
            node_instance = event.get('node_instance_id')
            if message.strip().endswith('nothing to do'):
                # All well and good, but let's not bloat the logs
                continue
            log_methods[level](
                '%s%s',
                '({}) '.format(node_instance) if node_instance else '',
                message,
            )


def list_snapshots(manager, logger):
    logger.info('Listing snapshots:')
    snapshots = manager.client.snapshots.list()
    for snapshot in snapshots:
        logger.info('%(id)s - %(status)s - %(error)s', snapshot)


def list_executions(manager, logger):
    logger.info('Listing executions:')
    executions = manager.client.executions.list(include_system_workflows=True)
    for execution in executions:
        logger.info('%(id)s (%(workflow_id)s) - %(status_display)s',
                    execution)
        if execution.get('error'):
            logger.warn('Execution %(id)s had error: %(error)s',
                        execution)


def list_capabilities(manager, deployment_id, logger):
    logger.info('Listing capabilities for %s', deployment_id)
    capabilities = manager.client.deployments.capabilities.get(
        deployment_id).capabilities
    for name, value in capabilities.items():
        logger.info(
            '%(dep)s capability %(name)s: %(value)s',
            {'dep': deployment_id, 'name': name, 'value': value},
        )


class DeploymentCreationError(Exception):
    """Deployment creation failed."""


def create_deployment(client, blueprint_id, deployment_id, logger,
                      inputs=None, skip_plugins_validation=False):
    logger.info('Creating deployment for %s', deployment_id)
    client.deployments.create(
        blueprint_id=blueprint_id,
        deployment_id=deployment_id,
        inputs=inputs or {},
        skip_plugins_validation=skip_plugins_validation,
    )

    logger.info('Waiting for deployment env creation for %s',
                deployment_id)
    executions = client.executions.list(deployment_id=deployment_id)
    for execution in executions:
        if execution.workflow_id == 'create_deployment_environment':
            wait_for_execution(
                client,
                execution,
                logger,
            )
            return
    raise DeploymentCreationError(
        'Deployment environment creation workflow not found for {}'.format(
            deployment_id,
        )
    )


class DeploymentDeletionError(Exception):
    """Deployment deletion failed."""


def delete_deployment(client, deployment_id, logger):
    logger.info('Deleting deployment %s', deployment_id)
    client.deployments.delete(deployment_id)
    # Allow a short delay to allow some time for the deletion
    time.sleep(0.5)

    for _ in range(20):
        found = False
        deployments = client.deployments.list()
        for deployment in deployments:
            if deployment['id'] == deployment_id:
                found = True
                logger.info('Still waiting for deployment %s to delete',
                            deployment_id)
                time.sleep(2)
                break

    if found:
        raise DeploymentDeletionError(
            'Deployment {} did not finish deleting.'.format(
                deployment_id,
            )
        )


@retrying.retry(stop_max_attempt_number=100, wait_fixed=250)
def wait_for_execution_status(example, execution_id, status):
    exec_list = example.manager.client.executions.list(id=execution_id)
    assert exec_list[0].status == status


@retrying.retry(stop_max_attempt_number=200, wait_fixed=250)
def get_deployment_by_blueprint(example, blueprint_id):
    deployment = example.manager.client.deployments.list(
        blueprint_id=blueprint_id)[0]
    return deployment


@retrying.retry(stop_max_attempt_number=100, wait_fixed=250)
def cancel_install(example, deployment_id):
    exec_list = example.manager.client.executions.list(
        workflow_id='install', deployment_id=deployment_id)
    assert exec_list[0].status == 'started'
    example.manager.client.executions.cancel(exec_list[0].id)
