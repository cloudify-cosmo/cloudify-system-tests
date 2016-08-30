#!/bin/bash

echo "Disable all jobs"
sudo -H -u $JENKINS_USER_NAME bash -c 'for f in $(find /var/lib/jenkins/jobs -name "config.xml"); do sed -i s/"disabled>false"/"disabled>true/" $f; done'
