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

import SoftLayer
import os
from cosmo_tester.framework.handlers import (
    BaseHandler,
    BaseCloudifyInputsConfigReader)

CLOUDIFY_TEST_NO_CLEANUP = 'CLOUDIFY_TEST_NO_CLEANUP'
MANAGER_BLUEPRINT = 'softlayer/softlayer.yaml'


class SoftLayerCleanupContext(BaseHandler.CleanupContext):

    def __init__(self, context_name, env):
        super(SoftLayerCleanupContext, self).__init__(context_name, env)

    def cleanup(self):
        super(SoftLayerCleanupContext, self).cleanup()
        resources_to_teardown = self.get_resources_to_teardown()
        if os.environ.get(CLOUDIFY_TEST_NO_CLEANUP):
            self.logger.warn('[{0}] SKIPPING cleanup: of the resources: {1}'
                             .format(self.context_name, resources_to_teardown))
            return
        self.logger.info('[{0}] Performing cleanup: will try removing these '
                         'resources: {1}'
                         .format(self.context_name, resources_to_teardown))

        leftovers = self.env.handler.remove_softlayer_resources(
            resources_to_teardown)
        self.logger.info('[{0}] Leftover resources after cleanup: {1}'
                         .format(self.context_name, leftovers))

    def get_resources_to_teardown(self):
        # TODO get softlayer resources to teardown
        pass


class CloudifySoftLayerInputsConfigReader(BaseCloudifyInputsConfigReader):

    def __init__(self, cloudify_config, manager_blueprint_path, **kwargs):
        super(CloudifySoftLayerInputsConfigReader, self).__init__(
            cloudify_config, manager_blueprint_path=manager_blueprint_path,
            **kwargs)

    @property
    def username(self):
        return self.config['username']

    @property
    def api_key(self):
        return self.config['api_key']

    @property
    def endpoint_url(self):
        return self.config['endpoint_url']

    @property
    def management_user_name(self):
        return self.config['agents_user']

    @property
    def management_key_path(self):
        return self.config['ssh_key_filename']


class SoftLayerHandler(BaseHandler):

    manager_blueprint = 'softlayer/softlayer.yaml'
    CleanupContext = SoftLayerCleanupContext
    CloudifyConfigReader = None
    _softrlayer_client = None

    def __init__(self, env):
        super(SoftLayerHandler, self).__init__(env)
        self.CloudifyConfigReader = CloudifySoftLayerInputsConfigReader

    def before_bootstrap(self):
        # TODO before bootstrap content
        pass

    def after_bootstrap(self, provider_context):
        # TODO after bootstrap content
        pass

    def after_teardown(self):
        # TODO after teardown content
        pass

    def _client_creds(self):
        return {
            'username': self.env.username,
            'api_key': self.env.api_key,
            'endpoint_url': self.env.endpoint_url
        }

    @property
    def softlayer_client(self):
        if self._softrlayer_client is None:
            creds = self._client_creds()
            self._softrlayer_client = SoftLayer.Client(**creds)
        return self._softrlayer_client

    def remove_softlayer_resources(self, resources_to_remove):
        # TODO remove resources
        pass


handler = SoftLayerHandler
