Cloudify System Tests
==================

* Master [![Circle CI](https://circleci.com/gh/cloudify-cosmo/cloudify-system-tests/tree/master.svg?&style=shield)](https://circleci.com/gh/cloudify-cosmo/cloudify-system-tests/tree/master)


This repository contains Cloudify's system tests which in most cases mean that the entire flow of:

1. Bootstrap using CLI.
2. CLI interaction with the Cloudify manager.
2. Blueprint uploading.
3. Deployment creation.
4. Workflows execution.
5. Manager teardown.

In addition, plugins functionality is tested and Cloudify's examples.

## Running System Tests

The following example demonstrates how to run Cloudify's node cellar example system test on an OpenStack environment:

* Create a new Python 2.7 virtualenv:
```
virtualenv venv
source venv/bin/activate
```

* Install Cloudify's CLI:
```
git clone https://github.com/cloudify-cosmo/cloudify-cli.git
pip install -e cloudify-cli -r cloudify-cli/dev-requirements.txt
```

* Install Cloudify's system tests framework:
```
git clone https://github.com/cloudify-cosmo/cloudify-system-tests.git
pip install -e cloudify-system-tests
```

* Install Cloudify's OpenStack plugin:
```
git clone https://github.com/cloudify-cosmo/cloudify-openstack-plugin.git
pip install -e cloudify-openstack-plugin
```

* Clone the cloudify-manager-blueprints repository (for the framework to be able to bootstrap a Cloudify manager):
```git clone https://github.com/cloudify-cosmo/cloudify-manager-blueprints.git```

* Create an inputs file for your environment (based on `cloudify-manager-blueprints/openstack/inputs.yaml.template`)

* Copy the sample handler configuration to your work dir (`cloudify-system-tests/suites/suites/sample-handler-configuration.yaml`).

* Set values for the following keys in the handler configuration file:
  - handler
  - inputs
  - manager_blueprint
  - properties

* Run a test using `nosetests`:
For tests located under the cloudify-system-tests package:
```
export HANDLER_CONFIGURATION=/path/to/sample-handler-configuration.yaml
nosetests -s cosmo_tester/test_suites/test_blueprints/nodecellar_test.py:OpenStackNodeCellarTest
```
similarly, for external tests located under the plugin package:
```
export HANDLER_CONFIGURATION=/path/to/sample-handler-configuration.yaml
nosetests -s system_tests/test_openstack_blueprint/nodecellar_test.py:OpenStackNodeCellarTest
```
Note that for external tests to exist in the python path, the plugins containing these tests must be installed with the -e option e.g 'pip install -e cloudify-openstack-plugin'.

## About Test Suites and suites.yaml:

The suits.yaml file defines properties and settings related to execution environments and specific environment properties.
The following section will cover some of the basic concepts implemented by this file.

* Tests in the cloudify-system-tests project are divided into separate test suites, each having it's own runtime environment and tests list.
  These test suites can be found in the suites.yaml file under 'test_suites'. A standard test suite would be defined like so:
  ```
  test_suites:
    openstack_blueprints_no_chef_puppet_docker_windows:
      requires: [openstack, datacentred]
      tests:
        - tests:
            - cosmo_tester/test_suites/test_blueprints
        - external:
            repo: cloudify-host-pool-plugin
          tests:
            - system_tests/manager

    ...
    ```
  Where:<br />
  * ```requires```: Used to specify the environment the tests may execute under.<br />
  * ```tests```: Used to define tests or test module paths and their package source repository.<br />
  * ```external```: Used to define the test package's source repository.<br />

* Upon execution of a single test or a test suite, a handler_configuration is assigned to it from an available configurations list.
  Using different handler_configurations allows for test suite executions to be distributed across all the available environment regions
  and run in parallel without interference.

  A standard handler configuration is defined like so:
  ```
  handler_configurations:
    lab_openstack_system_tests_region_a:
      handler: openstack_handler
      external:
        repo: cloudify-openstack-plugin
      inputs: inputs-lab-openstack.yaml
      manager_blueprint: openstack-manager-blueprint.yaml
      manager_blueprint_override: *openstack_manager_blueprint_override
      env: lab_openstack_system_tests_region_a
      tags: [openstack, lab]
      properties: lab_openstack_region_a_properties
      inputs_override:
        <<: *lab_openstack_credentials_inputs
        <<: *lab_openstack_region_a_inputs
        keystone_tenant_name: cloudify-cosmo-system-tests

    ...
  ```
  Where:<br />
  * ```handler```: Used to define the handler's module name which will be used as part of the test suite.
                  A handler is an environment specific module initialized prior to the test execution that implements these [BaseHandler](https://github.com/cloudify-cosmo/cloudify-system-tests/blob/master/cosmo_tester/framework/handlers.py#L86)
                  interface functions:<br />
                  - __before_bootstrap__<br />
                  - __after_bootstrap__<br />
                  - __after_teardown__<br />
                  The handler object also holds a cleanup class that implements a [BaseCleanupContext](https://github.com/cloudify-cosmo/cloudify-system-tests/blob/master/cosmo_tester/framework/handlers.py#L25) interface the following functions:<br />
                  - __cleanup__ - Cleans resources created by each test.<br />
                  - __cleanup_all__ - Cleans *all* resources, including resources that were not created by the test.<br />
                  To learn more about handlers, checkout the [openstack_handler](https://github.com/cloudify-cosmo/cloudify-openstack-plugin/blob/master/system_tests/openstack_handler.py)
  * ```external```: Used to define the handler's package source repository.<br />
  * ```inputs```: Used to define the name of the specific environment inputs.yaml file to use. Input files are located under '/suites/configurations'.<br />
  * ```manager_blueprint```: Used to define the manager blueprint file name. The actual file will be taken from the [cloudify-manager-blueprints](https://github.com/cloudify-cosmo/cloudify-manager-blueprints) repository.<br />
  * ```manager_blueprint_override```: Used to define specific overrides to the manager blueprint used by the test suite.<br />
  * ```env```: Used to define a unique environment identifier.<br />
  * ```tags```: Used to define the actual execution environment defined in the handler configuration.<br />
               A test suite may use any of the available handler_configurations as long as the 'requires' field matches the 'tags' stated in the test suite definition.<br />
  * ```properties```: Used to define environment related properties such as image_id for the specified region. e.g. for {my_image_id: afd32-312d} the following applies in tests: self.env.my_image_id == 'afd32-312d'.<br />
  * ```inputs_override```: any entry specified here will override (or add) an entry to the inputs.yaml file (or provider cloudify-config). dot notation may be used to override nested fields.<br />


