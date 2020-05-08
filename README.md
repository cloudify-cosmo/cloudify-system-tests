Cloudify System Tests
==================

* Master [![Circle CI](https://circleci.com/gh/cloudify-cosmo/cloudify-system-tests/tree/master.svg?&style=shield)](https://circleci.com/gh/cloudify-cosmo/cloudify-system-tests/tree/master)


The system tests framework uses pytest fixtures in order to create the required
resources for testing Cloudify.

## Updating requirements.txt

Install pip-tools, update dependencies as desired and run `pip-compile`, as noted in the requirements.txt header.

## Installation

### Install system tests framework

* Checkout the repository.
* cd cloudify-system-tests
* pip install -r requirements.txt && pip install --no-index -e .

### Install Terraform

Download terraform version 0.9.11 from [here](https://releases.hashicorp.com/terraform/0.9.11), and follow the installation instructions [here](https://www.terraform.io/intro/getting-started/install.html).


## Running tests

For tests running on an OpenStack environment, the framework assumes
a manager image is available in the environment (i.e. cloudify-manager-premium-4.0).

Before running a test, make sure to source your OpenStack openrc file.
The openrc file contains the authentication details for your OpenStack account.
Information about downloading it from an OpenStack environment can be found [here](https://docs.openstack.org/user-guide/common/cli-set-environment-variables-using-openstack-rc.html).

OpenStack openrc file example (my-openrc.sh):
```bash
#!/bin/bash

export OS_AUTH_URL=https://rackspace-api.cloudify.co:5000/v2.0
export OS_TENANT_NAME="idan-tenant"
export OS_PROJECT_NAME="idan-tenant"
export OS_USERNAME="idan"
export OS_PASSWORD="GUESS-ME"
export OS_REGION_NAME="RegionOne"
export OS_IDENTITY_API_VERSION=2
```

Make sure your openrc file is set to use the OpenStack v2 API in both `OS_AUTH_URL` and `OS_IDENTITY_API_VERSION` environment variables.

Source the openrc file:
```bash
source my-openrc.sh
```

Run:
```python
pytest -s cosmo_tester/test_suites/image_based_tests/simple_deployment_test.py::test_simple_deployment
```

**Please note it is important to run tests with the `-s` flag as the framework uses `Fabric` which is known to have problems with pytest's output capturing (https://github.com/pytest-dev/pytest/issues/1585).**

### Saving the Cloudify Manager's logs
In order to save the logs of tests, specify the path via an environment variable as follows:

`export CFY_LOGS_PATH_LOCAL=<YOUR-PATH-HERE>`

For example you may use:
```bash
export CFY_LOGS_PATH_LOCAL=~/cfy_logs/
```
which will save the logs to `~/cfy/_logs/` of only the failed tests.
