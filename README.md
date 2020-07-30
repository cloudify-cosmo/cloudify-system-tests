Cloudify System Tests
==================

* Master [![Circle CI](https://circleci.com/gh/cloudify-cosmo/cloudify-system-tests/tree/master.svg?&style=shield)](https://circleci.com/gh/cloudify-cosmo/cloudify-system-tests/tree/master)


The system tests framework uses pytest fixtures in order to create the required
resources for testing Cloudify.

## Installation

### Install system tests framework

* Checkout the repository.
* cd cloudify-system-tests
* pip install -r requirements.txt && pip install --no-index --no-deps -e .

## Running tests

The test framework requires a cloudify manager in order to create and manage test instances.
You will need to know the address of this manager and its admin password.
This manager will need to have network access to the platform you wish it to manage.
This manager will need to have the necessary plugin for your platform uploaded and shared with visibility set to global.

You will also need to have checked out the following repositories:
For all tests: cloudify-versions
For premium tests: cloudify-premium
For UI tests: cloudify-blueprint-composer, cloudify-stage
They are expected to exist in the same directory that the cloudify-system-tests directory exists, but this can be changed in the config.

The test framework assumes that manager images will exist, as defined in the schema.
To see expected images, look in the config under manager_image_names_centos and manager_image_names_rhel.

To see the schema including default values, run:
```bash
test-config schema
```

Configuration for the tests is expected to be found in test_config.yaml
This can be overridden when running pytest by passing the --config-location argument to pytest.

Basic configuration can be generated for your platform.
This basic configuration will be generated from the default approach for that platform (if one exists),
e.g. openstack environment generation will attempt to read the env vars normally provided by an openstackrc file.
For example, for openstack you can run:
```bash
test-config generate --platform openstack | tee test_config.yaml
```

You will then need to edit the file to set whether you are running premium tests, and populate any empty values.

You do not need to generate the test config every time you run tests.

You can now run a test:
```bash
pytest --pdb -s cosmo_tester/test_suites/image_based_tests/simple_deployment_test.py::test_simple_deployment
```
--pdb is recommended for manual test runs as this will pause test execution on failure and may allow you to gain valuable insight into the cause of the failure.
-s is recommended in order to ensure all test output is shown.

## Using the config in tests
There are two supported ways of accessing the config within tests.

In either case, use the test_config fixture in the test definition.

Then you can access platform specific details via .platform. This is not expected to be used outside of test_hosts, so please consider carefully if you really need it.
If you do need to use it, test_config.platform will provide the dict for the current target platform's relevant namespace, e.g. the openstack namespace.
As this is not expected to be frequently used, no example is provided below, so anyone looking for a quick solution to a problem will see the expected approach below.

The primary access method is as a dict, based on the schema.
e.g.
```python
def test_something(test_config):
    test_config['test_os_usernames']['windows_2012']
```

To see available keys in the schema, with descriptions:
```bash
test-config schema
```

## Updating requirements.txt

Install pip-tools, update dependencies as desired and run `pip-compile`, as noted in the requirements.txt header.
