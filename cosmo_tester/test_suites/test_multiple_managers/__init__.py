from cosmo_tester.framework.testenv import bootstrap, teardown

import requests

requests.packages.urllib3.disable_warnings()


def setUp():
    bootstrap()


def tearDown():
    teardown()
