#!/bin/bash
set -e

# check whether there is an xfs restore already
if [ "$(xfsrestore -I | grep 'session label:' | grep systests)" ]
then
  ctx logger info "XFS restore session exists. Skipping dump."
  exit 0
fi

# create an XFS restore session
  HOST_IP = $(ctx instance runtime_properties 'ip')
  VOLUME_ID=$(ctx instance runtime_properties 'xfs_volume_id')

  ctx logger info "Creating an XFS dump for host $HOST_IP. Might take up to 5 minutes..."
  sudo xfsdump -l0 -L systests -M systests -f /dev/${VOLUME_ID}p1 /
  ctx logger info "XFS dump created!"
