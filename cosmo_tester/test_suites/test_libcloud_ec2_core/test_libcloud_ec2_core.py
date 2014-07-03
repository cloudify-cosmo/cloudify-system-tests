__author__ = 'Oleksandr_Raskosov'


import unittest
import logging
import string
import random
import os
from copy import deepcopy
import yaml

from cloudify_libcloud import cloudify_libcloud_common as common
from libcloud.compute.types import NodeState


PREFIX_RANDOM_CHARS = 3
CLOUDIFY_TEST_CONFIG_PATH = 'ENTER-TEST-CONFIG-PATH-HERE'
CLOUDIFY_TEST_DEFAULTS_CONFIG_PATH = 'ENTER-DEFAULT-TEST-CONFIG-PATH-HERE'


class LibcloudEC2ProviderTest(unittest.TestCase):

    def setUp(self):
        logger = logging.getLogger(__name__)
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logger
        self.logger.level = logging.DEBUG
        self.logger.debug("Libcloud provider for EC2 test setUp() called")
        chars = string.ascii_uppercase + string.digits
        self.name_prefix = 'libcloud_ec2_test_{0}_'\
            .format(''.join(
                random.choice(chars) for x in range(PREFIX_RANDOM_CHARS)))
        self.provider_config = self._read_config(
            CLOUDIFY_TEST_CONFIG_PATH,
            CLOUDIFY_TEST_DEFAULTS_CONFIG_PATH)
        self._update_config(self.name_prefix, self.provider_config)
        self.provider_manager =\
            common.ProviderManager(provider_config=self.provider_config)
        self.driver = self.provider_manager.get_driver(self.provider_config)
        self.logger.debug("Libcloud provider for EC2 test setUp() done")

    def tearDown(self):
        self.logger.debug("Libcloud provider for EC2 test tearDown() called")
        created, created_names =\
            self._get_node_list_w_names(not_in_state=NodeState.TERMINATED)
        if created:
            self.logger.debug('Not all created nodes were deleted'
                              ' during teardown process.')
            for node in created:
                self.driver.server_controller.kill(node)
                self.logger.debug('Node \'{0}\' is deleted'.format(node.name))
        else:
            self.logger.debug('All created nodes were successfully deleted'
                              ' during teardown process.')

        created = self._get_sg_list_names()
        if created:
            self.logger.debug('Not all created security groups were deleted'
                              ' during teardown process.')
            to_delete = []
            for sg_name in created:
                group = self.driver.sg_controller.get_by_name(sg_name)
                self.driver.sg_controller.remove_rules(group)
                to_delete.append(group)
            for group in to_delete:
                self.driver.sg_controller.kill(group)
                self.logger.debug('Security group \'{0}\' is deleted'
                                  .format(group.name))
        else:
            self.logger.debug('All created security groups were successfully'
                              ' deleted during teardown process.')

        created, created_names = self._get_key_pair_list_w_names()
        if created:
            self.logger.debug('Not all created key pairs were deleted'
                              ' during teardown process.')
            for pair in created:
                self.driver.keypair_controller.kill(pair)
                self.logger.debug('Key pair \'{0}\' is deleted'
                                  .format(pair.name))
        else:
            self.logger.debug('All created key pairs were successfully deleted'
                              ' during teardown process.')
        self.logger.debug("Libcloud provider for EC2 test tearDown() done")

    def test(self):
        self.logger.debug("*****Libcloud test for EC2 started*****")

        self.logger.debug("Context validation started")
        validation_errors = {}
        self.provider_manager.validate(validation_errors)
        self.assertEqual(
            len(validation_errors.keys()),
            0,
            'ERROR: Context file validation error: '
            + ', '.join(validation_errors))
        self.logger.debug("Context validation finished")

        self.logger.debug("Provision started")
        public_ip, private_ip, ssh_key, ssh_user, provider_context =\
            self.provider_manager.provision()
        self.logger.debug("Provision finished")

        self.logger.debug("Validate provisioned")
        self._validate_provisioned(public_ip)
        self.logger.debug("Provisioning validated successfully")

        self.logger.debug("Teardown started")
        self.provider_manager.teardown(provider_context)
        self.logger.debug("Teardown finished")

        self.logger.debug("Validate after teardown completed")
        self._validate_teardowned()
        self.logger.debug("Teardown validated successfully")

        self.logger.debug("*****Libcloud test for EC2 finished*****")

    def _validate_provisioned(self, public_ip):
        networking_config = self.provider_config['networking']
        self._validate_networking(networking_config)
        compute_config = self.provider_config['compute']
        self._validate_compute(compute_config, public_ip)

    def _validate_networking(self, networking_config):
        created = self._get_sg_list_names()
        asg_name = networking_config['agents_security_group']['name']
        self.assertIn(
            asg_name,
            created,
            'ERROR: Agents security group wasn\'t created')
        self.assertIn(
            networking_config['management_security_group']['name'],
            created,
            'ERROR: Management security group wasn\'t created')
        created_len = len(created)
        self.assertEqual(
            created_len,
            2,
            'ERROR: Two security groups should be created'
            ' but created {0}: {1}'.format(created_len, ', '.join(created)))

    def _validate_key_pairs(self, compute_config):
        created, created_names = self._get_key_pair_list_w_names()
        self.assertIn(
            compute_config['management_server']['management_keypair']['name'],
            created_names,
            'ERROR: Management key pair wasn\'t created')
        self.assertIn(
            compute_config['agent_servers']['agents_keypair']['name'],
            created_names,
            'ERROR: Agents key pair wasn\'t created')
        created_len = len(created)
        self.assertEqual(
            created_len,
            2,
            'ERROR: Two key pairs should be created'
            ' but created {0}: {1}'
            .format(created_len, ', '.join(created_names)))

    def _validate_publick_ip(self, floating_ip_config, public_ip):
        if 'ip' in floating_ip_config:
            self.assertEqual(
                floating_ip_config['ip'],
                public_ip,
                'ERROR: Management server wrong public IP:'
                ' required {0} but is {1}'
                .format(floating_ip_config['ip'], public_ip))

    def _validate_management_server(self, management_config, public_ip):
        created, created_names = self._get_node_list_w_names()
        self.assertIn(
            management_config['instance']['name'],
            created_names,
            'ERROR: Management server wasn\'t created')
        created_len = len(created)
        self.assertEqual(
            created_len,
            1,
            'ERROR: The only one management server should be created'
            ' but created {0}: {1}'
            .format(created_len, ', '.join(created_names)))
        node = created[0]
        required_image = management_config['instance']['image']
        provided_image = node.extra['image_id']
        self.assertEqual(
            provided_image,
            required_image,
            'ERROR: Created management server wrong image:'
            ' required - {0}, provided - {1}'
            .format(required_image, provided_image))
        required_size = management_config['instance']['size']
        provided_size = node.extra['instance_type']
        self.assertEqual(
            provided_size,
            required_size,
            'ERROR: Created management server wrong size:'
            ' required - {0}, provided - {1}'
            .format(required_size, provided_size))
        if 'floating_ip' in management_config:
            self._validate_publick_ip(management_config['floating_ip'],
                                      public_ip)

    def _validate_compute(self, compute_config, public_ip):
        self._validate_key_pairs(compute_config)
        management_config = compute_config['management_server']
        self._validate_management_server(management_config, public_ip)

    def _validate_teardowned(self):
        created = self._get_sg_list_names()
        self.assertEqual(
            len(created),
            0,
            'ERROR: Not all created security groups were deleted'
            ' during teardown process: ' + ', '.join(created))
        created, created_names = self._get_key_pair_list_w_names()
        self.assertEqual(
            len(created),
            0,
            'ERROR: Not all created key pairs were deleted'
            ' during teardown process: ' + ', '.join(created))
        created, created_names =\
            self._get_node_list_w_names(not_in_state=NodeState.TERMINATED)
        self.assertEqual(
            len(created_names),
            0,
            'ERROR: Not all created nodes were deleted'
            ' during teardown process: ' + ', '.join(created_names))

    def _get_sg_list_names(self):
        created = []
        groups = self.driver.sg_controller.list()
        prfx = self.name_prefix
        for group in groups:
            if group.startswith(prfx):
                created.append(group)
        return created

    def _get_key_pair_list_w_names(self):
        created = []
        created_names = []
        keys = self.driver.keypair_controller.list()
        prfx = self.name_prefix
        for key in keys:
            name = key.name
            if name.startswith(prfx):
                created.append(key)
                created_names.append(name)
        return created, created_names

    def _get_node_list_w_names(self, not_in_state=None):
        created = []
        created_names = []
        nodes = self.driver.server_controller.list()
        prfx = self.name_prefix
        for node in nodes:
            name = node.name
            if name.startswith(prfx):
                if not_in_state:
                    if not_in_state != node.state:
                        created.append(node)
                        created_names.append(name)
                else:
                    created.append(node)
                    created_names.append(name)
        return created, created_names

    def _read_config(self, config_file_path, defaults_config_file_path):
        if not config_file_path:
            raise ValueError('Missing configuration file path')
        if not defaults_config_file_path:
            raise ValueError('Missing defaults configuration file path')

        if not os.path.exists(config_file_path) or not os.path.exists(
                defaults_config_file_path):
            if not os.path.exists(defaults_config_file_path):
                raise ValueError('Missing the defaults configuration file; '
                                 'expected to find it at {0}'.format(
                                     defaults_config_file_path))
            raise ValueError('Missing the configuration file;'
                             ' expected to find it at {0}'
                             .format(config_file_path))

        self.logger.debug('reading provider config files')
        with open(config_file_path, 'r') as config_file, \
                open(defaults_config_file_path, 'r') as defaults_config_file:

            self.logger.debug('safe loading user config')
            user_config = yaml.safe_load(config_file.read())

            self.logger.debug('safe loading default config')
            defaults_config = yaml.safe_load(defaults_config_file.read())

        self.logger.debug('merging configs')
        merged_config = self._deep_merge_dictionaries(user_config, defaults_config) \
            if user_config else defaults_config
        return merged_config

    def _deep_merge_dictionaries(self, overriding_dict, overridden_dict):
        merged_dict = deepcopy(overridden_dict)
        for k, v in overriding_dict.iteritems():
            if k in merged_dict and isinstance(v, dict):
                if isinstance(merged_dict[k], dict):
                    merged_dict[k] =\
                        self._deep_merge_dictionaries(v, merged_dict[k])
                else:
                    raise RuntimeError('type conflict at key {0}'.format(k))
            else:
                merged_dict[k] = deepcopy(v)
        return merged_dict

    def _update_config(self, prefix, config):
        for property_name in config.keys():
            property_item = config[property_name]
            if isinstance(property_item, str) and property_name == 'name':
                config[property_name] = prefix + property_item
            elif isinstance(property_item, dict):
                self._update_config(prefix, property_item)


if __name__ == '__main__':
    unittest.main()
