#!/bin/sh
# setting default if not set
CLOUD=${CLOUD:-openstack}

mkdir /oim/images

# clone latest Image yaml Files from github
git clone --depth 1 https://github.com/osism/openstack-image-manager.git /oim/src

# execute openstack-image-manager and update all images
/usr/local/bin/openstack-image-manager --cloud $CLOUD --images /oim/src/etc/images/ --filter \"$FILTER\"
