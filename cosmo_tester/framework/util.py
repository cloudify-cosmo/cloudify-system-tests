from contextlib import contextmanager
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

from cloudify_cli import env as cli_env
from cloudify_rest_client import CloudifyClient
from cloudify_rest_client.exceptions import (
    CloudifyClientError,
    UserUnauthorizedError,
)
from cloudify_cli.constants import CLOUDIFY_TENANT_HEADER

from .exceptions import ProcessExecutionError

import cosmo_tester
from cosmo_tester import resources


def sh_bake(command):
    """Make the command also print its stderr and stdout to our stdout/err."""
    # we need to pass the received lines back to the process._stdout/._stderr
    # so that they're not only printed out, but also saved as .stderr/.sdtout
    # on the return value or on the exception.
    return command.bake(_out=pass_stdout, _err=pass_stderr)


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
        username=username or cli_env.get_username(),
        password=password or cli_env.get_password(),
        tenant=tenant or cli_env.get_tenant_name(),
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
            'package-urls', filename,
        )
    )

    with open(package_url_file):
        return package_url_file.read()


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
def set_client_tenant(manager, tenant):
    if tenant:
        original = manager.client._client.headers[CLOUDIFY_TENANT_HEADER]

        manager.client._client.headers[CLOUDIFY_TENANT_HEADER] = tenant

    try:
        yield
    except Exception:
        raise
    finally:
        if tenant:
            manager.client._client.headers[CLOUDIFY_TENANT_HEADER] = original


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
    """Raised by `wait_for_execution` if the execution takes too long."""


class ExecutionFailed(Exception):
    """Raised by `wait_for_execution` if the execution fails."""


def wait_for_execution(manager, execution, logger, tenant=None,
                       new_password=None, timeout=(5*60)):
    logger.info(
        'Getting workflow execution [id={execution}]'.format(
            execution=execution['id'],
        )
    )
    current_time = time.time()
    # Timeout after ~5 minutes
    timeout_time = current_time + timeout
    password_updated = False
    output_events(manager, execution, logger, to_time=current_time)

    with set_client_tenant(manager, tenant):
        while True:
            try:
                execution = manager.client.executions.get(execution['id'])
            except UserUnauthorizedError:
                if new_password and not password_updated:
                    # This will happen on a restore with modified users
                    change_rest_client_password(manager, new_password)
                    password_updated = True
                else:
                    # We either shouldn't change the password, or did already.
                    raise

            prev_time = current_time
            current_time = time.time()

            output_events(manager, execution, logger, prev_time, current_time)

            if time.time() >= timeout_time:
                raise ExecutionTimeout(
                    'Execution timed out in state: {status}'.format(
                        status=execution.status,
                    )
                )

            if execution.status in execution.END_STATES:
                # Give time for any last second events
                time.sleep(2)
                output_events(manager, execution, logger,
                              current_time)

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


def output_events(manager, execution, logger, from_time=None, to_time=None):
    events = manager.client.events.list(
        execution_id=execution.id,
        _size=1000,
        include_logs=True,
        sort='reported_timestamp',
        from_datetime=convert_epoch_to_time_string(from_time),
        to_datetime=convert_epoch_to_time_string(to_time),
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
            logger.warn('Event level {} was unknown.'.format(level))
            logger.warn('Event was: {}'.format(event))
        else:
            log_methods[level](event.get('message', 'Message not found'))


def convert_epoch_to_time_string(inp):
    if inp:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(inp))
    else:
        return None


def change_rest_client_password(manager, new_password):
    manager.client = create_rest_client(manager.ip_address,
                                        tenant='default_tenant',
                                        password=new_password)
