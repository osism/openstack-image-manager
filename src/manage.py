import logging
import sys
import time
import openstack
import requests
import yaml

from decimal import Decimal, ROUND_UP
from natsort import natsorted
from oslo_config import cfg
from openstack.connection import Connection
from openstack.image.v2.image import Image


def import_image(conn: Connection, name: str, image: dict, url: str, tag: str) -> None:
    '''
    Create a new image in Glance and upload it using the web-download method

    params:
        conn - OpenStack connection object
        name - name of the image to import
        image - image dict from images.yml
        url - download URL of the image
        tag - tag from CONF.tag and --tag
    '''
    logging.info("Importing image %s" % name)

    properties = {
        'container_format': 'bare',
        'disk_format': image['format'],
        'min_disk': image.get('min_disk', 0),
        'min_ram': image.get('min_ram', 0),
        'name': name,
        'tags': [tag],
        'visibility': 'private'
    }

    new_image = conn.image.create_image(**properties)
    conn.image.import_image(new_image, method='web-download', uri=url)

    while True:
        try:
            status = conn.image.get_image(new_image).status
            if status != 'active':
                logging.info("Waiting for import to complete...")
                time.sleep(10.0)
            else:
                break

        except Exception as e:
            logging.error("Exception while importing image %s\n%s" % (name, e))
            return


def get_images(conn: Connection, tag: str = None, use_os_hidden: bool = False) -> dict:
    '''
    Returns all images from Glance that match the specified tag from --tag

    params:
        conn - OpenStack connection object
        tag - tag from CONF.tag and --tag
        use_os_hidden - bool from CONF.use_os_hidden and --use-os-hidden

    returns:
        a dict containing all images as openstack.image.v2.image.Image objects
    '''
    result = {}

    for image in conn.image.images():
        if tag in image.tags and (image.visibility == 'public' or image.owner == conn.current_project_id):
            result[image.name] = image
            logging.debug("Managed image '%s' (tags = %s)" % (image.name, image.tags))
        else:
            logging.debug("Unmanaged image '%s' (tags = %s)" % (image.name, image.tags))

    if use_os_hidden:
        for image in conn.image.images(**{'os_hidden': True}):
            if tag in image.tags and (image.visibility == 'public' or image.owner == conn.current_project_id):
                result[image.name] = image
                logging.debug("Managed hidden image '%s' (tags = %s)" % (image.name, image.tags))
            else:
                logging.debug("Unmanaged hidden image '%s' (tags = %s)" % (image.name, image.tags))

    return result


def process_image(conn: Connection, image: dict, versions: dict, sorted_versions: list, CONF: cfg.ConfigOpts) -> tuple:
    '''
    Process one image from images.yml
    Check if the image already exists in Glance and import it if not

    params:
        conn - OpenStack connection object
        image - image dict from images.yml
        versions - dict of image version from images.yml
        sorted_versions - natsorted version list
        CONF - oslo_config.cfg.ConfigOpts object

    returns:
        tuple with (uploaded_image, previous_image, imported_image, existing_images)
    '''
    cloud_images = get_images(conn, CONF.tag, CONF.use_os_hidden)

    existing_images = set()
    uploaded_image = False
    imported_image = None
    previous_image = None

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
                existence = cloud_images[image['name']]['properties']['internal_version'] == version

        elif image['multi'] and len(sorted_versions) > 1 and version == sorted_versions[-1] and not existence:
            previous = "%s (%s)" % (image['name'], sorted_versions[-2])
            existence = previous in cloud_images and image['name'] in cloud_images

        elif image['multi'] and len(sorted_versions) > 1 and version == sorted_versions[-2] and not existence:
            existence = image['name'] in cloud_images

        elif image['multi'] and len(sorted_versions) == 1:
            existence = image['name'] in cloud_images

        if not existence and not (CONF.latest and len(sorted_versions) > 1 and version != sorted_versions[-1]):

            url = versions[version]['url']
            r = requests.head(url)
            logging.info("Tested URL %s: %s" % (url, r.status_code))

            if r.status_code not in [200, 302]:
                logging.error("Skipping '%s' due to HTTP status code %s" % (name, r.status_code))
                return uploaded_image, previous_image, imported_image, existing_images

            if image['multi'] and image['name'] in cloud_images:
                previous_image = cloud_images[image['name']]

            if not CONF.dry_run:
                import_image(conn, name, image, url, CONF.tag)
                logging.info("Import of '%s' successfully completed, reloading images" % name)

                cloud_images = get_images(conn, CONF.tag, CONF.use_os_hidden)
                imported_image = cloud_images[name]
                uploaded_image = True

        elif CONF.latest and version != sorted_versions[-1]:
            logging.info("Skipping image '%s' (only importing the latest version of images from type multi)" % name)

        if image['multi']:
            existing_images.add(image['name'])
        else:
            existing_images.add(name)

        if uploaded_image:
            set_properties(conn, image, name, versions, version, CONF)

    return uploaded_image, previous_image, imported_image, existing_images


def set_properties(
    conn: Connection,
    image: dict,
    name: str,
    versions: dict,
    version: str,
    CONF: cfg.ConfigOpts
) -> None:
    '''
    Set image properties and tags based on the configuration from images.yml

    params:
        conn - OpenStack connection object
        image - image dict from images.yml
        name - name of the image including the version string
        versions - list of image version from images.yml
        version - currently processed version
        CONF - oslo_config.cfg.ConfigOpts object
    '''
    cloud_images = get_images(conn, CONF.tag, CONF.use_os_hidden)

    if name in cloud_images:
        logging.info("Checking parameters of '%s'" % name)

        cloud_image = cloud_images[name]
        properties = cloud_image.properties
        real_image_size = int(Decimal(cloud_image.size / 2**30).quantize(Decimal('1.'), rounding=ROUND_UP))

        if 'min_disk' in image and image['min_disk'] != cloud_image.min_disk:
            logging.info("Setting min_disk: %s != %s" % (image['min_disk'], cloud_image.min_disk))
            conn.image.update_image(cloud_image.id, **{'min_disk': int(image['min_disk'])})

        if ('min_disk' in image and real_image_size > image['min_disk']) or 'min_disk' not in image:
            logging.info("Setting min_disk = %d" % real_image_size)
            conn.image.update_image(cloud_image.id, **{'min_disk': real_image_size})

        if 'min_ram' in image and image['min_ram'] != cloud_image.min_ram:
            logging.info("Setting min_ram: %s != %s" % (image['min_ram'], cloud_image.min_ram))
            conn.image.update_image(cloud_image.id, **{'min_ram': int(image['min_ram'])})

        if 'build_date' in versions[version]:
            logging.info("Setting image_build_date = %s" % versions[version]['build_date'])
            image['meta']['image_build_date'] = versions[version]['build_date']

        if CONF.use_os_hidden:
            if 'hidden' in versions[version]:
                logging.info("Setting os_hidden = %s" % versions[version]['hidden'])
                conn.image.update_image(cloud_image.id, **{'os_hidden': versions[version]['hidden']})

            elif version != natsorted(versions.keys())[-1:]:
                logging.info("Setting os_hidden = True")
                conn.image.update_image(cloud_image.id, **{'os_hidden': True})

        logging.info("Setting internal_version = %s" % version)
        image['meta']['internal_version'] = version

        logging.info("Setting image_original_user = %s" % image['login'])
        image['meta']['image_original_user'] = image['login']

        if image['multi'] and 'os_version' in versions[version]:
            image['meta']['os_version'] = versions[version]['os_version']
        elif not image['multi']:
            image['meta']['os_version'] = version

        for tag in image['tags']:
            if tag not in cloud_image.tags:
                logging.info("Adding tag %s" % (tag))
                conn.image.add_tag(cloud_image.id, tag)

        for tag in cloud_image.tags:
            if tag not in image['tags']:
                logging.info("Deleting tag %s" % (tag))
                conn.image.remove_tag(cloud_image.id, tag)

        for property in properties:
            if property in image['meta']:
                if image['meta'][property] != properties[property]:
                    logging.info("Setting property %s: %s != %s" %
                                 (property, properties[property], image['meta'][property]))
                    conn.image.update_image(cloud_image.id, **{property: str(image['meta'][property])})

            elif property not in ['self', 'schema', 'stores'] or not property.startswith('os_'):
                # FIXME: handle deletion of properties
                logging.debug("Deleting property %s" % (property))

        for property in image['meta']:
            if property not in properties:
                logging.info("Setting property %s: %s" % (property, image['meta'][property]))
                conn.image.update_image(cloud_image.id, **{property: str(image['meta'][property])})

        logging.info("Checking status of '%s'" % name)
        if cloud_image.status != image['status'] and image['status'] == 'deactivated':
            logging.info("Deactivating image '%s'" % name)
            conn.image.deactivate_image(cloud_image.id)

        elif cloud_image.status != image['status'] and image['status'] == 'active':
            logging.info("Reactivating image '%s'" % name)
            conn.image.reactivate_image(cloud_image.id)

        logging.info("Checking visibility of '%s'" % name)
        if 'visibility' in versions[version]:
            visibility = versions[version]['visibility']
        else:
            visibility = image['visibility']

        if cloud_image.visibility != visibility:
            logging.info("Setting visibility of '%s' to '%s'" % (name, visibility))
            conn.image.update_image(cloud_image.id, visibility=visibility)


def rename_images(
    conn: Connection,
    name: str,
    sorted_versions: list,
    previous_image: Image,
    imported_image: Image,
    CONF: cfg.ConfigOpts
) -> None:
    '''
    Rename old images in Glance (only applies to images of type multi)

    params:
        conn - OpenStack connection object
        name - the name of the image from images.yml
        sorted_versions - natsorted version list
        previous_image - openstack.image.v2.image.Imageobject of the previous latest image
        imported_image - openstack.image.v2.image.Image object of the imported image
        CONF - oslo_config.cfg.ConfigOpts object
    '''
    cloud_images = get_images(conn, CONF.tag, CONF.use_os_hidden)

    if len(sorted_versions) > 1:
        latest = "%s (%s)" % (name, sorted_versions[-1])
        previous_latest = "%s (%s)" % (name, sorted_versions[-2])

        if name in cloud_images and previous_latest not in cloud_images:
            logging.info("Renaming %s to %s" % (name, previous_latest))
            conn.image.update_image(cloud_images[name].id, name=previous_latest)

        if latest in cloud_images:
            logging.info("Renaming %s to %s" % (latest, name))
            conn.image.update_image(cloud_images[latest].id, name=name)

    elif len(sorted_versions) == 1 and name in cloud_images:
        previous_latest = "%s (%s)" % (name, previous_image['properties']['internal_version'])

        logging.info("Renaming old latest '%s' to '%s'" % (name, previous_latest))
        conn.image.update_image(previous_image.id, name=previous_latest)

        logging.info("Renaming imported image '%s' to '%s'" % (imported_image.name, name))
        conn.image.update_image(imported_image.id, name=name)

    elif len(sorted_versions) == 1:
        latest = "%s (%s)" % (name, sorted_versions[-1])

        if latest in cloud_images:
            logging.info("Renaming %s to %s" % (latest, name))
            conn.image.update_image(cloud_images[latest].id, name=name)


def manage_outdated_images(conn: Connection, managed_images: set, CONF: cfg.ConfigOpts) -> None:
    '''
    Delete the image or change their visibility or hide them (depending on the CLI params)

    params:
        conn - OpenStack connection object
        managed_images - set of managed images
        CONF - oslo_config.cfg.ConfigOpts object

    raises:
        Exception - when the image is still in use and cannot be deleted
        Exception - when the image cannot be deactivated or its visibility cannot be changed
    '''
    cloud_images = get_images(conn, CONF.tag, CONF.use_os_hidden)

    for image in [x for x in cloud_images if x not in managed_images]:
        cloud_image = cloud_images[image]
        if CONF.delete and CONF.yes_i_really_know_what_i_do:
            try:
                logging.info("Deactivating image '%s'" % image)
                conn.image.deactivate_image(cloud_image.id)

                logging.info("Setting visibility of '%s' to 'community'" % image)
                conn.image.update_image(cloud_image.id, visibility='community')

                logging.info("Deleting %s" % image)
                conn.image.delete_image(cloud_image.id)
            except Exception as e:
                logging.info("%s is still in use and cannot be deleted\n %s" % (image, e))

        else:
            logging.warning("Image %s should be deleted" % image)
            try:
                if CONF.deactivate:
                    logging.info("Deactivating image '%s'" % image)
                    conn.image.deactivate_image(cloud_image.id)

                if CONF.hide:
                    cloud_image = cloud_images[image]
                    logging.info("Setting visibility of '%s' to 'community'" % image)
                    conn.image.update_image(cloud_image.id, visibility='community')
            except Exception as e:
                logging.error('An Exception occurred: %s' % e)


def main(CONF: cfg.ConfigOpts) -> None:
    '''
    Read images.yml and process each image
    Rename outdated images when not dry-running

    params:
        CONF - oslo_config.cfg.ConfigOpts object
    '''
    with open(CONF.images) as fp:
        data = yaml.load(fp, Loader=yaml.SafeLoader)
        conf_images = data.get('images', [])

    conn = openstack.connect(cloud=CONF.cloud)

    logging.debug("cloud = %s" % CONF.cloud)
    logging.debug("dry-run = %s" % CONF.dry_run)
    logging.debug("images = %s" % CONF.images)
    logging.debug("tag = %s" % CONF.tag)
    logging.debug("yes-i-really-know-what-i-do = %s" % CONF.yes_i_really_know_what_i_do)

    REQUIRED_KEYS = [
        'format',
        'name',
        'login',
        'status',
        'versions',
        'visibility',
    ]
    managed_images = set()

    for image in conf_images:

        for required_key in REQUIRED_KEYS:
            if required_key not in image:
                logging.error("'%s' lacks the necessary key %s" % (image['name'], required_key))
                continue

        if CONF.name and CONF.name != image['name']:
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

        uploaded_image, previous_image, imported_image, existing_images = \
            process_image(conn, image, versions, sorted_versions, CONF)

        if uploaded_image and image['multi']:
            rename_images(conn, image['name'], sorted_versions, previous_image, imported_image, CONF)
        managed_images = set.union(managed_images, existing_images)

    if not CONF.dry_run:
        manage_outdated_images(conn, managed_images, CONF)


if __name__ == '__main__':
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

    logging.basicConfig(format='%(asctime)s %(levelname)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

    main(CONF)
