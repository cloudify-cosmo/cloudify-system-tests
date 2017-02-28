
import logging
import os
import shutil
import sys
import tempfile

from path import Path
import pytest
import sh
import yaml

from cosmo_tester.framework import util


@pytest.fixture(scope='module')
def logger(request):
    logger = logging.getLogger(request.module.__name__)
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter(fmt='%(asctime)s [%(levelname)s] '
                                      '[%(name)s] %(message)s',
                                  datefmt='%H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


@pytest.fixture(scope='module')
def module_tmpdir(request, logger):
    suffix = request.module.__name__
    temp_dir = Path(tempfile.mkdtemp(suffix=suffix))
    logger.info('Created temp folder: %s', temp_dir)

    yield temp_dir

    logger.info('Deleting temp folder: %s', temp_dir)
    shutil.rmtree(temp_dir)


class SSHKey(object):

    def __init__(self, private_key_path, public_key_path):
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path


@pytest.fixture(scope='module')
def ssh_key(module_tmpdir, logger):
    private_key_path = module_tmpdir / 'key.pem'
    public_key_path = module_tmpdir / 'key.pem.pub'
    logger.info('Creating temporary SSH keys at: %s', module_tmpdir)
    if os.system("ssh-keygen -t rsa -f {} -q -N ''".format(
            private_key_path)) != 0:
        raise IOError('Error creating SSH key: {}'.format(private_key_path))
    if os.system('chmod 400 {}'.format(private_key_path)) != 0:
        raise IOError('Error setting private key file permission')

    yield SSHKey(private_key_path, public_key_path)

    public_key_path.remove()
    private_key_path.remove()


@pytest.fixture(scope='module')
def attributes(request, logger):
    attributes_file = util.get_resource_path('attributes.yaml')
    logger.info('Loading attributes from: %s', attributes_file)
    with open(attributes_file, 'r') as f:
        attrs = util.AttributesDict(yaml.load(f))
        return attrs


@pytest.fixture(scope='module')
def cfy(request):
    cfy = util.sh_bake(sh.cfy)
    return cfy
