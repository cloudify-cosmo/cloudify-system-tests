
import logging
import sys

import pytest


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
