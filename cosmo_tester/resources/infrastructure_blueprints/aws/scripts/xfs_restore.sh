#!/bin/bash
set -e

# check whether there is an xfs restore already
if [ -z "$(xfsrestore -I | grep 'session label:' | grep systests)" ]
then
  ctx logger warning "No XFS restore session found. Aborting."
  exit 1
fi

# restore from XFS dump
  HOST_IP = $(ctx instance runtime_properties 'ip')
  VOLUME_ID=$(ctx instance runtime_properties 'xfs_volume_id')

  ctx logger info "Restoring from an XFS dump for host $HOST_IP. Might take up to 1 minute..."
  sudo xfsrestore -L test -f /dev/${VOLUME_ID}p1 /
  ctx logger info "XFS dump restored sucessfully!"
