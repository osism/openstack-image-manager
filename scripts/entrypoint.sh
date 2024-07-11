#!/bin/sh
# setting default if not set
SCHEDULE=${SCHEDULE:-0 1 * * 7}
CLOUD=${CLOUD:-openstack}

mkdir /oim/images

env >> /etc/environment
# build cronjob entry
croncmd="git clone --depth 1 https://github.com/osism/openstack-image-manager.git /oim/src; rm /oim/images/*; cp /oim/src/etc/images/* /oim/images; rm -rf /oim/src &&  /usr/local/bin/openstack-image-manager --cloud $CLOUD --images /oim/images/ --filter \"$FILTER\" > /proc/1/fd/1 2>/proc/1/fd/2"

echo "SHELL=/bin/bash" >> /etc/cron.d/openstack-image-manager
echo "BASH_ENV=/etc/environment" >> /etc/cron.d/openstack-image-manager
echo "$SCHEDULE root $croncmd" >> /etc/cron.d/openstack-image-manager

# execute CMD
exec "$@"
