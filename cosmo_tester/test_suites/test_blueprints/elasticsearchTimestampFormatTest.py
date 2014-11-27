__author__ = 'hagai'

'''
this test checks Elasticsearch Timestamp Format.
it creates events by uploading a blueprint and creating deployment.
after creating events the test connects to Elasticsearch and compares
Timestamp Format of the events to a regular expression.

This test requires access to the management on port 9200 (elastic search",
The rule is added by create_elasticsearch_rule
'''

import re
import time

from elasticsearch import Elasticsearch
from neutronclient.common.exceptions import NeutronClientException

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.git_helper import clone
from cosmo_tester.framework.util import YamlPatcher
from cosmo_tester.framework.handlers.openstack import OpenstackHandler

DEFAULT_EXECUTE_TIMEOUT = 1800

NODECELLAR_URL = "https://github.com/cloudify-cosmo/" \
                 "cloudify-nodecellar-example.git"


class ElasticsearchTimestampFormatTest(TestCase):

    def create_elasticsearch_rule(self):
        os_handler = OpenstackHandler(self.env)
        neutron_client =  os_handler.openstack_clients()[1]
        sgr = {
            'direction': 'ingress',
            'ethertype': 'IPv4',
            'port_range_max': '9200',
            'port_range_min': '9200',
            'protocol': 'tcp',
            'remote_group_id': None,
            'remote_ip_prefix': '0.0.0.0/0',
            }

        mng_sec_grp_name = self.env.management_security_group

        mng_sec_grp = neutron_client.\
            list_security_groups(name=mng_sec_grp_name)['security_groups'][0]

        sg_id = mng_sec_grp['id']
        sgr['security_group_id'] = sg_id
        rule_id = neutron_client.create_security_group_rule(
            {'security_group_rule': sgr})['security_group_rule']['id']
        return rule_id

    def delete_elasticsearch_rule(self, rule):
        os_handler = OpenstackHandler(self.env)
        neutron_client =  os_handler.openstack_clients()[1]
        neutron_client.delete_security_group_rule(rule)

    def test_events_timestamp_format(self):
        try:
            print "Creating elastic-search security rule"
            rule = self.create_elasticsearch_rule()
            time.sleep(20)  # allow rule to be created
        except NeutronClientException as e:
            rule = None
            print "NeutronClientException({0}). Resuming".format(str(e))
            pass

        self.repo_dir = clone(NODECELLAR_URL, self.workdir)
        self.blueprint_yaml = self.repo_dir / 'openstack-blueprint.yaml'
        self.modify_blueprint()
        try:
            self.cfy.upload_blueprint(self.test_id, self.blueprint_yaml, False)
        except Exception:
            self.fail('failed to upload the blueprint')
        time.sleep(5)
        #  connect to Elastic search
        try:
            es = Elasticsearch(self.env.management_ip + ':9200')
        except Exception:
            self.fail('failed to connect Elasticsearch')
        #  get events from events index
        res = es.search(index="cloudify_events",
                        body={"query": {"match_all": {}}})
        print("res Got %d Hits:" % res['hits']['total'])
        #  check if events were created
        if(0 == (res['hits']['total'])):
            self.fail('there are no events with '
                      'timestamp in index cloudify_events')
        #  loop over all the events and compare timestamp to regular expression
        for hit in res['hits']['hits']:
            if not (re.match('\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.\d{3}',
                             (str("%(timestamp)s" % hit["_source"])))):
                self.fail('Got {0}. Does not match format '
                          'YYYY-MM-DD HH:MM:SS.***'
                          .format((str("%(timestamp)s" % hit["_source"]))))

        if rule is not None:
            print "Deleting elastic-search rule"
            self.delete_elasticsearch_rule(rule)

        return

    def modify_blueprint(self):
        with YamlPatcher(self.blueprint_yaml) as patch:
            vm_type_path = 'node_types.vm_host.properties'
            patch.merge_obj('{0}.server.default'.format(vm_type_path), {
                'image_name': self.env.ubuntu_image_name,
                'flavor_name': self.env.flavor_name
            })
        return
