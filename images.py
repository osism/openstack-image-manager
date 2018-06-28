#!/usr/bin/env python

import os
import shutil
import subprocess
import tempfile
import yaml

import requests
import shade

CLOUD= os.environ.get('CLOUD', 'images')
REQUIRED_KEYS = [
    'name',
    'format'
]

with open("images.yml") as fp:
    images = yaml.load(fp)

cloud = shade.openstack_cloud(cloud=CLOUD)
cloud_images = {}

for image in cloud.list_images():
    if image.is_public or image.owner == cloud.current_project_id:
        cloud_images[image.name] = image

for image in images:

    skip = False

    # check required keys

    for required_key in REQUIRED_KEYS:
        if required_key not in image:
            print("'%s' lacks the necessary key %s" % (image['name'], required_key))
            skip = True
    if skip:
        continue

    print("Processing '%s'" % image['name'])

    # check existence
    existence = image['name'] in cloud_images

    if not existence:
        # check image url

        r = requests.head(image['url'])
        print("Test URL %s: %s" % (image['url'], r.status_code))

        if r.status_code not in [200]:
            print("Skipping '%s'" % image['name'])
            continue

        r = requests.get(image['url'], stream=True)
        if r.status_code in [200]:
            _, p = tempfile.mkstemp(prefix='images-')
            print("Saving '%s' --> %s" % (image['name'], p))
            with open(p, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)        

            if image['format'] != 'raw':
                _, p_raw = tempfile.mkstemp(prefix='images-')
                print ("Converting '%s' --> %s" % (image['name'], p_raw))
                subprocess.call(['qemu-img', 'convert', p, p_raw])

                print("Removing %s" % p)
                os.unlink(p)

                p = p_raw

            print("Uploading %s" % p)
            i = cloud.create_image(
                image['name'],
                filename=p,
                wait=True,
                disk_format='raw',
                container_format='bare',
                meta=image['meta'],
                min_disk=image.get('min_disk', 0),
                min_ram=image.get('min_ram', 0),
            )

            print("Removing %s" % p)
            os.unlink(p)
    else:
        print("Checking parameters of '%s'" % image['name'])

        cloud_image = cloud_images[image['name']]
        properties = cloud_image.properties

        if 'min_disk' in image and image['min_disk'] != cloud_image.min_disk:
            print("Setting min_disk: %s != %s" % (image['min_disk'], cloud_image.min_disk))
            cloud.update_image_properties(name_or_id=cloud_image.id, min_disk=image['min_disk'])

        if 'min_ram' in image and image['min_ram'] != cloud_image.min_ram:
            print("Setting min_ram: %s != %s" % (image['min_ram'], cloud_image.min_ram))
            cloud.update_image_properties(name_or_id=cloud_image.id, min_ram=image['min_ram'])

        for property in properties:
            if property in image['meta']:
                if image['meta'][property] != properties[property]:
                    print("Setting %s: %s != %s" % (property, properties[property], image['meta'][property]))
                    meta = {property: image['meta'][property]}
                    cloud.update_image_properties(name_or_id=cloud_image.id, meta=meta)
            else:
                # FIXME: handle deletion of properties
                pass

        for property in image['meta']:
            if property not in properties:
                # FIXME: handle addition of properties
                pass
