########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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

import os
import re
import sys
import glob
import json
import yaml
import errno
import shlex
import base64
import socket
import logging
import platform
import requests
import retrying
import subprocess
from os import makedirs
from tempfile import mkstemp
from contextlib import contextmanager

from openstack import connection as openstack_connection
from path import Path

from cloudify_cli import env as cli_env
from cloudify_rest_client import CloudifyClient
from cloudify_cli.constants import CLOUDIFY_TENANT_HEADER

from .exceptions import ProcessExecutionError

import cosmo_tester
from cosmo_tester import resources


OS_USERNAME_ENV = 'OS_USERNAME'
OS_PASSWORD_ENV = 'OS_PASSWORD'
OS_TENANT_NAME_ENV = 'OS_TENANT_NAME'
OS_PROJECT_NAME_ENV = 'OS_PROJECT_NAME'
OS_AUTH_URL_ENV = 'OS_AUTH_URL'


class AttributesDict(dict):
    __getattr__ = dict.__getitem__


def get_attributes(logger=logging, resources_dir=None):
    attributes_file = get_resource_path('attributes.yaml', resources_dir)
    logger.info('Loading attributes from: %s', attributes_file)
    with open(attributes_file, 'r') as f:
        attrs = AttributesDict(yaml.load(f))
        return attrs


def get_cli_version():
    return cli_env.get_version_data()['version']


def get_openstack_server_password(server_id, private_key_path=None):
    """Since openstacksdk does not contain this functionality and adding
    python-novaclient as a dependency creates a dependencies hell, it is
    easier to just call the relevant OpenStack REST API call for retrieving
    the server's password."""

    conn = create_openstack_client()
    compute_endpoint = conn.session.get_endpoint(service_type='compute')
    url = '{}/servers/{}/os-server-password'.format(
        compute_endpoint, server_id
    )
    headers = conn.session.get_auth_headers()
    headers['Content-Type'] = 'application/json'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            'OpenStack get password response status (%d) != 200: {}'.format(
                r.status_code, r.text
            )
        )
    password = r.json()['password']
    if private_key_path:
        return _decrypt_password(password, private_key_path)
    else:
        return password


def _decrypt_password(password, private_key_path):
    """Base64 decodes password and unencrypts it with private key.

    Requires openssl binary available in the path.
    """
    unencoded = base64.b64decode(password)
    cmd = ['openssl', 'rsautl', '-decrypt', '-inkey', private_key_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    out, err = proc.communicate(unencoded)
    proc.stdin.close()
    if proc.returncode:
        raise RuntimeError(err)
    return out


def get_openstack_config():
    return {
        'username': os.environ[OS_USERNAME_ENV],
        'password': os.environ[OS_PASSWORD_ENV],
        'tenant_name': os.environ.get(OS_TENANT_NAME_ENV,
                                      os.environ[OS_PROJECT_NAME_ENV]),
        'auth_url': os.environ[OS_AUTH_URL_ENV]
    }


def create_openstack_client():
    conn = openstack_connection.Connection(
        auth_url=os.environ[OS_AUTH_URL_ENV],
        project_name=os.environ[OS_PROJECT_NAME_ENV],
        username=os.environ[OS_USERNAME_ENV],
        password=os.environ[OS_PASSWORD_ENV]
    )
    return conn


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


def get_yaml_as_dict(yaml_path):
    return yaml.load(Path(yaml_path).text())


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


def get_plugin_wagon_urls():
    """Get plugin wagon urls from the cloudify-versions repository."""

    def _fetch(branch):
        plugin_urls_location = url_format.format(branch=branch)
        return requests.get(plugin_urls_location)

    branch = os.environ.get('BRANCH_NAME_CORE', 'master')
    url_format = 'https://raw.githubusercontent.com/cloudify-cosmo/' \
                 'cloudify-versions/{branch}/packages-urls/plugin-urls.yaml'
    response = _fetch(branch=branch)
    if response.status_code != 200:
        if branch == 'master':
            raise RuntimeError(
                'Fetching the versions yaml from the {0} branch of '
                '"cloudify-versions" failed. Status was {1}'.format(
                    branch, response.status_code))
        response = _fetch(branch='master')
        if response.status_code != 200:
            raise RuntimeError(
                'Fetching the versions yaml from the master branch of '
                '"cloudify-versions" failed. '
                'Status was {0}'.format(response.status_code))

    return yaml.load(response.text)['plugins']


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


def get_cli_package_url(platform):
    # Override URLs if they are provided in the config
    config_cli_urls = get_attributes()['cli_urls_override']

    if config_cli_urls.get(platform):
        url = config_cli_urls[platform]
    else:
        if is_community():
            filename = 'cli-packages.yaml'
            packages_key = 'cli_packages_urls'
        else:
            filename = 'cli-premium-packages.yaml'
            packages_key = 'cli_premium_packages_urls'
        url = yaml.load(_get_package_url(filename))[packages_key][platform]

    test_cli_package_url(url)

    return url


def get_manager_install_rpm_url():
    return yaml.load(_get_package_url('manager-install-rpm.yaml'))


def _get_contents_from_github(repo, resource_path):
    branch = os.environ.get('BRANCH_NAME_CORE', 'master')
    url = (
        'https://raw.githubusercontent.com/cloudify-cosmo/'
        '{repo}/{branch}/{resource_path}'
    ).format(repo=repo, branch=branch, resource_path=resource_path)
    session = get_authenticated_git_session()
    r = session.get(url)
    if not r.ok:
        raise RuntimeError(
            'Error retrieving github content from {url}'.format(url=url)
        )
    return r.text


def _get_package_url(filename):
    """Gets the package URL(s).
    They will be retrieved either from GitHub (if (GITHUB_TOKEN exists in env)
    or locally if the cloudify-premium or cloudify-versions repository is
    checked out under the same folder the cloudify-system-tests repo is
    checked out.
    """
    if is_community():
        repo = 'cloudify-versions'
    else:
        repo = 'cloudify-premium'

    if os.environ.get('GITHUB_TOKEN'):
        return _get_contents_from_github(
            repo=repo,
            resource_path='packages-urls/{filename}'.format(
                filename=filename,
            )
        )
    else:
        package_url_file = (
            Path(cosmo_tester.__file__).dirname() /
            '..' / '..' / repo / 'packages-urls' / filename
        ).abspath()
        if not package_url_file.exists():
            raise IOError('File containing {0} URL not '
                          'found: {1}'.format(filename, package_url_file))
        return package_url_file.text()


class YamlPatcher(object):

    pattern = re.compile(r'(.+)\[(\d+)\]')
    set_pattern = re.compile(r'(.+)\[(\d+|append)\]')

    def __init__(self, yaml_path, is_json=False, default_flow_style=True):
        self.yaml_path = Path(yaml_path)
        self.obj = yaml.load(self.yaml_path.text()) or {}
        self.is_json = is_json
        self.default_flow_style = default_flow_style

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_type:
            output = json.dumps(self.obj) if self.is_json else yaml.safe_dump(
                self.obj, default_flow_style=self.default_flow_style)
            self.yaml_path.write_text(output)

    def merge_obj(self, obj_prop_path, merged_props):
        obj = self._get_object_by_path(obj_prop_path)
        for key, value in merged_props.items():
            obj[key] = value

    def set_value(self, prop_path, new_value):
        obj, prop_name = self._get_parent_obj_prop_name_by_path(prop_path)
        list_item_match = self.set_pattern.match(prop_name)
        if list_item_match:
            prop_name = list_item_match.group(1)
            obj = obj[prop_name]
            if not isinstance(obj, list):
                raise AssertionError('Cannot set list value for not list item '
                                     'in {0}'.format(prop_path))
            raw_index = list_item_match.group(2)
            if raw_index == 'append':
                obj.append(new_value)
            else:
                obj[int(raw_index)] = new_value
        else:
            obj[prop_name] = new_value

    def append_value(self, prop_path, value):
        obj, prop_name = self._get_parent_obj_prop_name_by_path(prop_path)
        obj[prop_name] = obj[prop_name] + value

    def _split_path(self, path):
        # allow escaping '.' with '\.'
        parts = re.split(r'(?<![^\\]\\)\.', path)
        return [p.replace(r'\.', '.').replace('\\\\', '\\') for p in parts]

    def _get_object_by_path(self, prop_path):
        current = self.obj
        for prop_segment in self._split_path(prop_path):
            match = self.pattern.match(prop_segment)
            if match:
                index = int(match.group(2))
                property_name = match.group(1)
                if property_name not in current:
                    self._raise_illegal(prop_path)
                if type(current[property_name]) != list:
                    self._raise_illegal(prop_path)
                current = current[property_name][index]
            else:
                if prop_segment not in current:
                    current[prop_segment] = {}
                current = current[prop_segment]
        return current

    def delete_property(self, prop_path, raise_if_missing=True):
        obj, prop_name = self._get_parent_obj_prop_name_by_path(prop_path)
        if prop_name in obj:
            obj.pop(prop_name)
        elif raise_if_missing:
            raise KeyError('cannot delete property {0} as its not a key in '
                           'object {1}'.format(prop_name, obj))

    def _get_parent_obj_prop_name_by_path(self, prop_path):
        split = self._split_path(prop_path)
        if len(split) == 1:
            return self.obj, prop_path
        parent_path = '.'.join(p.replace('.', r'\.') for p in split[:-1])
        parent_obj = self._get_object_by_path(parent_path)
        prop_name = split[-1]
        return parent_obj, prop_name

    @staticmethod
    def _raise_illegal(prop_path):
        raise RuntimeError('illegal path: {0}'.format(prop_path))


@retrying.retry(stop_max_attempt_number=20, wait_fixed=5000)
def assert_snapshot_created(manager, snapshot_id, attributes):
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


def is_community():
    image_type = get_attributes()['image_type']

    # We check the image type is valid to avoid unanticipated effects from
    # typos.
    community_image_types = [
        'community',
    ]
    valid_image_types = community_image_types + [
        'premium',
    ]

    if image_type not in valid_image_types:
        raise ValueError(
            'Invalid image_type: {specified}.\n'
            'Valid image types are: {valid}'.format(
                specified=image_type,
                valid=', '.join(valid_image_types),
            )
        )

    return image_type in community_image_types


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


def prepare_and_get_test_tenant(test_param, manager, cfy):
    """
        Prepares a tenant for testing based on the test name (or other
        identifier passed in as 'test_param'), and returns the name of the
        tenant that should be used for this test.
    """
    default_openstack_plugin = get_attributes()['default_openstack_plugin']

    if is_community():
        tenant = 'default_tenant'
        # It is expected that the plugin is already uploaded for the
        # default tenant
    else:
        tenant = test_param
        cfy.tenants.create(tenant)
        manager.upload_plugin(default_openstack_plugin,
                              tenant_name=tenant)
    return tenant


def mkdirs(folder_path):
    try:
        makedirs(folder_path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(folder_path):
            pass
        else:
            raise


def is_redhat():
    return 'redhat' in platform.platform()


def run(command, retries=0, stdin=b'', ignore_failures=False,
        globx=False, shell=False, env=None, stdout=None, logger=logging):
    def subprocess_preexec():
        cfy_umask = 0022
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


def sudo(command, *args, **kwargs):
    if isinstance(command, str):
        command = shlex.split(command)
    if 'env' in kwargs:
        command = ['sudo', '-E'] + command
    else:
        command.insert(0, 'sudo')
    return run(command=command, *args, **kwargs)


def remove(path_to_remove, ignore_failure=False, logger=logging):
    logger.debug('Removing {0}...'.format(path_to_remove))
    # sudo(['rm', '-rf', path_to_remove], ignore_failures=ignore_failure)


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

    try:
        yield temp_config_path
    finally:
        remove(temp_config_path)


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
        remove(csr_path)

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


class ExecutionWaiting(Exception):
    """
    raised by `wait_for_execution` if it should be retried
    """


class ExecutionFailed(Exception):
    """
    raised by `wait_for_execution` if a bad state is reached
    """


def retry_if_not_failed(exception):
    return not isinstance(exception, ExecutionFailed)


@retrying.retry(
    stop_max_delay=5 * 60 * 1000,
    wait_fixed=10000,
    retry_on_exception=retry_if_not_failed,
)
def wait_for_execution(manager, execution, logger):
    logger.info(
        'Getting workflow execution [id={execution}]'.format(
            execution=execution['id'],
        )
    )
    execution = manager.client.executions.get(execution['id'])
    logger.info('- execution.status = %s', execution.status)
    if execution.status not in execution.END_STATES:
        raise ExecutionWaiting(execution.status)
    if execution.status != execution.TERMINATED:
        logger.warning('Execution failed')
        raise ExecutionFailed(
            '{status}: {error}'.format(
                status=execution.status,
                error=execution['error'],
            )
        )
    logger.info('Execution complete')
    return execution


def _get_release_dict_by_name(
        item_name, dict_or_list):
    if isinstance(dict_or_list, dict):
        return dict_or_list.get(item_name)
    elif isinstance(dict_or_list, list):
        for item in dict_or_list:
            if item['name'] == item_name:
                return item
    raise Exception('No item named {0} in {1}'.format(
        item_name, dict_or_list)
    )


def get_authenticated_git_session(git_token=None):
    git_token = git_token or os.environ.get('GITHUB_TOKEN')
    session = requests.Session()
    if git_token:
        session.headers['Authorization'] = 'token %s' % git_token
    return session


def download_asset(repository_path,
                   release_name,
                   asset_name,
                   save_location,
                   git_token=None):

    session = get_authenticated_git_session(git_token)
    releases = session.get(
        'https://api.github.com/repos/{0}/releases'.format(
            repository_path))
    if not releases.ok:
        raise RuntimeError(
            'Failed to authenticate to {0}, reason: {1}'.format(
                releases.url, releases.reason))

    release = _get_release_dict_by_name(release_name, releases.json())
    asset = _get_release_dict_by_name(asset_name, release['assets'])
    session.headers['Accept'] = 'application/octet-stream'

    with session.get(asset['url'], stream=True) as response:
        if not response.ok:
            raise Exception(
                'Failed to download {0}'.format(asset['url']))
        with open(save_location, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
