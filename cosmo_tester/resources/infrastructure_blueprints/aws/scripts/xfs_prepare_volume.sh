#!/bin/bash
set -e

# identify the still not partitioned volume
VOLUME_ID=`lsblk -o NAME,TYPE -ds |  awk '$2 == "disk" {print $1}'`

# store volume id
ctx instance runtime_properties 'xfs_volume_id' VOLUME_ID

if [ -z $VOLUME_ID ]
then
  ctx logger warning "No XFS dump volume found. Proceeding without."
  exit 0
fi

# partition the volume and format for XFS + install the xfsdump tool
echo "n
p
1


w" | sudo fdisk /dev/$VOLUME_ID
sudo mkfs -t xfs /dev/${$VOLUME_ID}p1
sudo yum install -y xfsdump
