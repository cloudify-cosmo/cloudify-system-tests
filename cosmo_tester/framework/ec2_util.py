__author__ = 'Oleksandr_Raskosov'


class EC2CloudifyConfigReader(object):

    def __init__(self, cloudify_config):
        self.config = cloudify_config

    @property
    def management_server_name(self):
        return self.config['compute']['management_server']['instance']['name']

    @property
    def management_server_floating_ip(self):
        return self.config['compute']['management_server']['floating_ip']

    @property
    def agent_key_path(self):
        return self.config['compute']['agent_servers']['agents_keypair']['private_key_path']

    @property
    def managment_user_name(self):
        return self.config['compute']['management_server'][
            'user_on_management']

    @property
    def management_key_path(self):
        return self.config['compute']['management_server'][
            'management_keypair']['private_key_path']

    @property
    def agent_keypair_name(self):
        return self.config['compute']['agent_servers']['agents_keypair'][
            'name']

    @property
    def management_keypair_name(self):
        return self.config['compute']['management_server'][
            'management_keypair']['name']

    @property
    def agents_security_group(self):
        return self.config['networking']['agents_security_group']['name']

    @property
    def management_security_group(self):
        return self.config['networking']['management_security_group']['name']
