from decimal import Decimal, ROUND_UP
import logging
import sys
import time

from natsort import natsorted
from oslo_config import cfg
import openstack
import os_client_config
import requests
import yaml

PROJECT_NAME = 'images'
CONF = cfg.CONF
opts = [
    cfg.BoolOpt('deactivate', help='Deactivate images that should be deleted', default=False),
    cfg.BoolOpt('debug', help='Enable debug logging', default=False),
    cfg.BoolOpt('delete', help='Delete images that should be delete', default=False),
    cfg.BoolOpt('dry-run', help='Do not really do anything', default=False),
    cfg.BoolOpt('hide', help='Hide images that should be deleted', default=False),
    cfg.BoolOpt('latest', help='Only import the latest version of images from type multi', default=True),
    cfg.BoolOpt('use-os-hidden', help='Use the os_hidden property', default=False),
    cfg.BoolOpt('use-raw-images', help='Use raw images', default=True),
    cfg.BoolOpt('yes-i-really-know-what-i-do', help='Really delete images', default=False),
    cfg.StrOpt('cloud', help='Cloud name in clouds.yaml', default='images'),
    cfg.StrOpt('images', help='Path to the images.yml file', default='etc/images.yml'),
    cfg.StrOpt('name', help='Image name to process', default=None),
    cfg.StrOpt('tag', help='Name of the tag used to identify managed images', default='managed_by_osism')
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)

if CONF.debug:
    level = logging.DEBUG
else:
    level = logging.INFO
logging.basicConfig(format='%(asctime)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

REQUIRED_KEYS = [
    'format',
    'name',
    'status',
    'versions',
    'visibility',
]

with open(CONF.images) as fp:
    data = yaml.load(fp, Loader=yaml.SafeLoader)
    images = data.get('images', [])

conn = openstack.connect(cloud=CONF.cloud)
glance = os_client_config.make_client("image", cloud=CONF.cloud)


def import_image(glance, name, image, url):
    logging.info("Importing image %s" % name)

    disk_format = image['format']

    # NOTE: https://docs.openstack.org/glance/latest/admin/interoperable-image-import.html#the-image-conversion
    if CONF.use_raw_images:
        disk_format = "raw"

    input = {
        'image_properties': {
            'container_format': 'bare',
            'disk_format': disk_format,
            'min_disk': image.get('min_disk', 0),
            'min_ram': image.get('min_ram', 0),
            'name': name,
            'tags': [CONF.tag],
            'visibility': 'private'
        }
    }

    new_image = glance.images.create(**input['image_properties'])

    glance.images.image_import(new_image.id, method='web-download', uri=url)

    while True:
        try:
            status = glance.images.get(new_image.id).status
            if status != 'active':
                logging.info("Waiting for import to complete...")
                time.sleep(10.0)
            else:
                break

        except Exception as e:
            logging.error("Exception while importing %s" % e)
            time.sleep(5.0)
            pass


def get_images(conn, glance):
    result = {}

    for image in conn.list_images():
        if CONF.tag in image.tags and (image.is_public or image.owner == conn.current_project_id):
            result[image.name] = image
            logging.debug("Managed image '%s' (tags = %s)" % (image.name, image.tags))
        else:
            logging.debug("Unmanaged image '%s' (tags = %s)" % (image.name, image.tags))

    if CONF.use_os_hidden:
        for image in glance.images.list(**{'filters': {'os_hidden': True}}):
            hidden_image = conn.get_image_by_id(image.id)
            if CONF.tag in hidden_image.tags and (hidden_image.is_public or
               hidden_image.owner == conn.current_project_id):
                result[hidden_image.name] = hidden_image
                logging.debug("Managed hidden image '%s' (tags = %s)" % (hidden_image.name, hidden_image.tags))
            else:
                logging.debug("Unmanaged hidden image '%s' (tags = %s)" % (hidden_image.name, hidden_image.tags))

    return result


# show runtime parameters

logging.debug("cloud = %s" % CONF.cloud)
logging.debug("dry-run = %s" % CONF.dry_run)
logging.debug("images = %s" % CONF.images)
logging.debug("tag = %s" % CONF.tag)
logging.debug("yes-i-really-know-what-i-do = %s" % CONF.yes_i_really_know_what_i_do)

# get all existing images

cloud_images = get_images(conn, glance)

# manage existing images and add new ones

existing_images = []

for image in images:
    skip = False

    for required_key in REQUIRED_KEYS:
        if required_key not in image:
            logging.error("'%s' lacks the necessary key %s" % (image['name'], required_key))
            skip = True

    if CONF.name and CONF.name != image['name']:
        skip = True

    if skip:
        continue

    logging.info("Processing '%s'" % image['name'])

    versions = dict()
    for version in image['versions']:
        versions[str(version['version'])] = {
            'url': version['url']
        }
        if 'visibility' in version:
            versions[version['version']]['visibility'] = version['visibility']

        if 'os_version' in version:
            versions[version['version']]['os_version'] = version['os_version']

        if 'hidden' in version:
            versions[version['version']]['hidden'] = version['hidden']

    sorted_versions = natsorted(versions.keys())
    image['tags'].append(CONF.tag)

    if 'os_distro' in image['meta']:
        image['tags'].append("os:%s" % image['meta']['os_distro'])

    uploaded_new_latest_image = False
    for version in sorted_versions:
        if image['multi']:
            name = "%s (%s)" % (image['name'], version)
        else:
            name = "%s %s" % (image['name'], version)

        logging.info("Processing image '%s'" % name)

        logging.info("Checking existence of '%s'" % name)
        existence = name in cloud_images

        if image['multi'] and CONF.latest and version == sorted_versions[-1] and not existence:
            existence = image['name'] in cloud_images
            if existence:
                existence = cloud_images[image['name']]['internal_version'] == version
        elif image['multi'] and len(sorted_versions) > 1 and version == sorted_versions[-1] and not existence:
            previous = "%s (%s)" % (image['name'], sorted_versions[-2])
            existence = previous in cloud_images and image['name'] in cloud_images
        elif image['multi'] and len(sorted_versions) > 1 and version == sorted_versions[-2] and not existence:
            existence = image['name'] in cloud_images
        elif image['multi'] and len(sorted_versions) == 1:
            existence = image['name'] in cloud_images

        if not existence and not (CONF.latest and len(sorted_versions) > 1 and version != sorted_versions[-1]):

            if image['multi'] and image['name'] in cloud_images:
                the_previous_current_image = cloud_images[image['name']]

            url = versions[version]['url']

            r = requests.head(url)
            logging.info("Tested URL %s: %s" % (url, r.status_code))

            if r.status_code not in [200, 302]:
                logging.warning("Skipping '%s'" % name)
                continue

            if not CONF.dry_run:
                import_image(glance, name, image, url)

                if image['multi'] and len(sorted_versions) == 1 and image['name'] in cloud_images:
                    previous_current = "%s (%s)" % (image['name'], the_previous_current_image['internal_version'])
                    logging.info("Renaming old latest '%s' to '%s'" % (image['name'], previous_current))
                    glance.images.update(the_previous_current_image.id, name=previous_current)

                logging.info("Import of '%s' successfully completed, reload images" % name)
                cloud_images = get_images(conn, glance)

                if version == sorted_versions[-1]:
                    uploaded_new_latest_image = True

            existing_images.append(name)

        elif CONF.latest and version != sorted_versions[-1]:
            logging.info("Skipping image '%s' (only importing the latest version of images from type multi)" % name)

        if image['multi'] and version == sorted_versions[-1] and image['name'] in cloud_images and CONF.latest:
            name = image['name']

        existing_images.append(name)

        if name in cloud_images:
            logging.info("Checking parameters of '%s'" % name)

            cloud_image = cloud_images[name]
            properties = cloud_image.properties
            real_image_size = int(Decimal(cloud_image.size / 2**30).quantize(Decimal('1.'), rounding=ROUND_UP))
            tags = cloud_image.tags

            if 'min_disk' in image and image['min_disk'] != cloud_image.min_disk:
                logging.info("Setting min_disk: %s != %s" % (image['min_disk'], cloud_image.min_disk))

                if not CONF.dry_run:
                    glance.images.update(cloud_image.id, **{'min_disk': int(image['min_disk'])})

            if 'min_disk' in image and real_image_size > image['min_disk']:
                logging.warning("Invalid value for min_disk: %d > %d" % (real_image_size, image['min_disk']))
                logging.info("Setting min_disk = %d" % real_image_size)

                if not CONF.dry_run:
                    glance.images.update(cloud_image.id, **{'min_disk': real_image_size})

            if 'min_disk' not in image:
                logging.info("Setting min_disk = %d" % real_image_size)

                if not CONF.dry_run:
                    glance.images.update(cloud_image.id, **{'min_disk': real_image_size})

            if 'min_ram' in image and image['min_ram'] != cloud_image.min_ram:
                logging.info("Setting min_ram: %s != %s" % (image['min_ram'], cloud_image.min_ram))

                if not CONF.dry_run:
                    glance.images.update(cloud_image.id, **{'min_ram': int(image['min_ram'])})

            if 'build_date' in versions[version]:
                logging.info("Setting image_build_date = %s" % versions[version]['build_date'])
                image['meta']['image_build_date'] = versions[version]['build_date']

            if CONF.use_os_hidden:
                if 'hidden' in versions[version]:
                    logging.info("Setting os_hidden = %s" % versions[version]['hidden'])
                    if not CONF.dry_run:
                        glance.images.update(cloud_image.id, **{'os_hidden': versions[version]['hidden']})

                elif version not in sorted_versions[-1:]:
                    logging.info("Setting os_hidden = True")
                    if not CONF.dry_run:
                        glance.images.update(cloud_image.id, **{'os_hidden': True})

            logging.info("Setting internal_version = %s" % version)
            image['meta']['internal_version'] = version

            logging.info("Setting image_original_user = %s" % image['login'])
            image['meta']['image_original_user'] = image['login']

            if not image['multi']:
                image['meta']['os_version'] = version
            else:
                if 'os_version' in versions[version]:
                    image['meta']['os_version'] = versions[version]['os_version']

            for tag in image['tags']:
                if tag not in tags:
                    logging.info("Adding tag %s" % (tag))

                    if not CONF.dry_run:
                        glance.image_tags.update(cloud_image.id, tag)

            for tag in tags:
                if tag not in image['tags']:
                    logging.info("Deleting tag %s" % (tag))

                    if not CONF.dry_run:
                        glance.image_tags.delete(cloud_image.id, tag)

            for property in properties:
                if property in image['meta']:
                    if image['meta'][property] != properties[property]:
                        logging.info("Setting property %s: %s != %s" %
                                     (property, properties[property], image['meta'][property]))

                        if not CONF.dry_run:
                            glance.images.update(cloud_image.id, **{property: str(image['meta'][property])})
                elif property not in ['self', 'schema', 'os_hash_algo', 'os_hidden', 'os_hash_value', 'stores']:
                    # FIXME: handle deletion of properties
                    logging.info("Deleting property %s" % (property))

            for property in image['meta']:
                if property not in properties:
                    logging.info("Setting property %s: %s" % (property, image['meta'][property]))

                    if not CONF.dry_run:
                        glance.images.update(cloud_image.id, **{property: str(image['meta'][property])})

            logging.info("Checking status of '%s'" % name)
            if cloud_image.status != image['status'] and image['status'] == 'deactivated':
                logging.info("Deactivating image '%s'" % name)

                if not CONF.dry_run:
                    glance.images.deactivate(cloud_image.id)
            elif cloud_image.status != image['status'] and image['status'] == 'active':
                logging.info("Reactivating image '%s'" % name)

                if not CONF.dry_run:
                    glance.images.reactivate(cloud_image.id)

            logging.info("Checking visibility of '%s'" % name)
            if image['multi'] and image['visibility'] == 'public' and version not in sorted_versions[-3:]:
                visibility = 'community'
            elif 'visibility' in versions[version]:
                visibility = versions[version]['visibility']
            else:
                visibility = image['visibility']

            if cloud_image.visibility != visibility:
                logging.info("Setting visibility of '%s' to '%s'" % (name, visibility))

                if not CONF.dry_run:
                    glance.images.update(cloud_image.id, visibility=visibility)

    if image['multi'] and len(sorted_versions) > 1 and uploaded_new_latest_image:
        name = image['name']
        latest = "%s (%s)" % (image['name'], sorted_versions[-1])
        current = "%s (%s)" % (image['name'], sorted_versions[-2])

        if name in cloud_images and current not in cloud_images:
            logging.info("Renaming %s to %s" % (name, current))

            if not CONF.dry_run:
                glance.images.update(cloud_images[name].id, name=current)

        if latest in cloud_images:
            logging.info("Renaming %s to %s" % (latest, name))

            if not CONF.dry_run:
                glance.images.update(cloud_images[latest].id, name=name)

        cloud_images = get_images(conn, glance)

    elif image['multi'] and len(sorted_versions) == 1:
        name = image['name']
        latest = "%s (%s)" % (image['name'], sorted_versions[-1])

        if latest in cloud_images:
            logging.info("Renaming %s to %s" % (latest, name))

            if not CONF.dry_run:
                glance.images.update(cloud_images[latest].id, name=name)

# check if images need to be removed

cloud_images = get_images(conn, glance)

for image in [x for x in cloud_images if x not in existing_images]:
    if not CONF.dry_run and CONF.delete and CONF.yes_i_really_know_what_i_do:
        cloud_image = cloud_images[image]

        try:
            logging.info("Deactivating image '%s'" % image)
            glance.images.deactivate(cloud_image.id)

            logging.info("Setting visibility of '%s' to 'community'" % image)
            glance.images.update(cloud_image.id, visibility='community')

            logging.info("Deleting %s" % image)
            glance.images.delete(cloud_image.id)

        except Exception:
            logging.info("%s is still in use and cannot be deleted" % image)

    else:
        logging.debug("Image %s should be deleted" % image)
        if not CONF.dry_run and CONF.deactivate:
            cloud_image = cloud_images[image]

            logging.info("Deactivating image '%s'" % image)
            glance.images.deactivate(cloud_image.id)

        if not CONF.dry_run and CONF.hide:
            cloud_image = cloud_images[image]
            logging.info("Setting visibility of '%s' to 'community'" % image)
            glance.images.update(cloud_image.id, visibility='community')
