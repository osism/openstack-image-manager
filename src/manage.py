import logging
import sys
import time
import openstack
import requests
import yaml
import os

from decimal import Decimal, ROUND_UP
from natsort import natsorted
from oslo_config import cfg
from openstack.image.v2.image import Image


class ImageManager:

    def __init__(self) -> None:
        self.exit_with_error = False

    def create_cli_args(self):
        PROJECT_NAME = 'images'
        self.CONF = cfg.CONF
        opts = [
            cfg.BoolOpt('deactivate', help='Deactivate images that should be deleted', default=False),
            cfg.BoolOpt('debug', help='Enable debug logging', default=False),
            cfg.BoolOpt('delete', help='Delete images that should be delete', default=False),
            cfg.BoolOpt('dry-run', help='Do not really do anything', default=False),
            cfg.BoolOpt('hide', help='Hide images that should be deleted', default=False),
            cfg.BoolOpt('latest', help='Only import the latest version of images from type multi', default=True),
            cfg.BoolOpt('use-os-hidden', help='Use the os_hidden property', default=False),
            cfg.BoolOpt('yes-i-really-know-what-i-do', help='Really delete images', default=False),
            cfg.StrOpt('cloud', help='Cloud name in clouds.yaml', default='openstack'),
            cfg.StrOpt('images', help='Path to the directory containing all image files', default='etc/images/'),
            cfg.ListOpt('name', help='List of image names to process', default=list()),
            cfg.StrOpt('tag', help='Name of the tag used to identify managed images', default='managed_by_osism')
        ]
        if not self.CONF._args:
            self.CONF.register_cli_opts(opts)
        self.CONF(sys.argv[1:], project=PROJECT_NAME)

        if self.CONF.debug:
            level = logging.DEBUG
        else:
            level = logging.INFO

        logging.basicConfig(format='%(asctime)s %(levelname)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

    def read_image_files(self) -> list:
        ''' Read all YAML files in etc/images/ '''
        image_files = []
        for file in os.listdir(self.CONF.images):
            if os.path.isfile(os.path.join(self.CONF.images, file)):
                image_files.append(file)

        all_images = []
        for file in image_files:
            with open(os.path.join(self.CONF.images, file)) as fp:
                data = yaml.load(fp, Loader=yaml.SafeLoader)
                images = data.get('images')
                for image in images:
                    all_images.append(image)
        return all_images

    def main(self) -> None:
        '''
        Read all files in etc/images/ and process each image
        Rename outdated images when not dry-running
        '''
        if "OS_AUTH_URL" in os.environ:
            self.conn = openstack.connect()
        else:
            self.conn = openstack.connect(cloud=self.CONF.cloud)

        logging.debug("cloud = %s" % self.CONF.cloud)
        logging.debug("dry-run = %s" % self.CONF.dry_run)
        logging.debug("images = %s" % self.CONF.images)
        logging.debug("tag = %s" % self.CONF.tag)
        logging.debug("yes-i-really-know-what-i-do = %s" % self.CONF.yes_i_really_know_what_i_do)

        REQUIRED_KEYS = [
            'format',
            'name',
            'login',
            'status',
            'versions',
            'visibility',
        ]
        managed_images = set()
        all_images = self.read_image_files()

        # get all active managed images, so they don't get deleted when using --name
        cloud_images = self.get_images()
        for image in cloud_images:
            if cloud_images[image].visibility == "public":
                managed_images.add(image)

        for image in all_images:

            for required_key in REQUIRED_KEYS:
                if required_key not in image:
                    logging.error("'%s' lacks the necessary key %s" % (image['name'], required_key))
                    self.exit_with_error = True
                    continue

            if self.CONF.name and image['name'] not in self.CONF.name:
                continue

            logging.debug("Processing '%s'" % image['name'])

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
            image['tags'].append(self.CONF.tag)

            if 'os_distro' in image['meta']:
                image['tags'].append("os:%s" % image['meta']['os_distro'])

            existing_images, imported_image, previous_image = self.process_image(image, versions, sorted_versions)
            managed_images = set.union(managed_images, existing_images)

            if imported_image and image['multi']:
                self.rename_images(image['name'], sorted_versions, imported_image, previous_image)

        if not self.CONF.dry_run:
            self.manage_outdated_images(managed_images)

        if self.exit_with_error:
            sys.exit('\nERROR: One or more errors occurred during the execution of the program, '
                     'please check the output.')

    def import_image(self, image: dict, name: str, url: str) -> Image:
        '''
        Create a new image in Glance and upload it using the web-download method

        Params:
            image: image dict from images.yml
            name: name of the image to import
            url: download URL of the image
        '''
        logging.info("Importing image %s" % name)

        properties = {
            'container_format': 'bare',
            'disk_format': image['format'],
            'min_disk': image.get('min_disk', 0),
            'min_ram': image.get('min_ram', 0),
            'name': name,
            'tags': [self.CONF.tag],
            'visibility': 'private'
        }

        new_image = self.conn.image.create_image(**properties)
        self.conn.image.import_image(new_image, method='web-download', uri=url)

        while True:
            try:
                imported_image = self.conn.image.get_image(new_image)
                if imported_image.status != 'active':
                    logging.info("Waiting for import to complete...")
                    time.sleep(10.0)
                else:
                    break
            except Exception as e:
                logging.error("Exception while importing image %s\n%s" % (name, e))
                self.exit_with_error = True
        return imported_image

    def get_images(self) -> dict:
        '''
        Load all images from OpenStack and filter by the tag set by the --tag CLI option

        Returns:
            a dict containing all matching images as openstack.image.v2.image.Image objects
        '''
        result = {}

        for image in self.conn.image.images():
            if self.CONF.tag in image.tags and (image.visibility == 'public'
                                                or image.owner == self.conn.current_project_id):
                result[image.name] = image
                logging.debug("Managed image '%s' (tags = %s)" % (image.name, image.tags))
            else:
                logging.debug("Unmanaged image '%s' (tags = %s)" % (image.name, image.tags))

        if self.CONF.use_os_hidden:
            for image in self.conn.image.images(**{'os_hidden': True}):
                if self.CONF.tag in image.tags and (image.visibility == 'public'
                                                    or image.owner == self.conn.current_project_id):
                    result[image.name] = image
                    logging.debug("Managed hidden image '%s' (tags = %s)" % (image.name, image.tags))
                else:
                    logging.debug("Unmanaged hidden image '%s' (tags = %s)" % (image.name, image.tags))
        return result

    def process_image(self, image: dict, versions: dict, sorted_versions: list) -> tuple:
        '''
        Process one image from etc/images/
        Check if the image already exists in Glance and import it if not

        Params:
            image: image dict from images.yml
            versions: versions dict generated by main()
            sorted_versions: list with all sorted image versions

        Returns:
            Tuple with (existing_images, imported_image, previous_image)
        '''
        cloud_images = self.get_images()

        existing_images = set()
        imported_image = None
        previous_image = None

        for version in sorted_versions:
            if image['multi']:
                name = "%s (%s)" % (image['name'], version)
            else:
                name = "%s %s" % (image['name'], version)

            logging.info("Processing image '%s'" % name)
            logging.debug("Checking existence of '%s'" % name)
            existence = name in cloud_images

            if image['multi'] and self.CONF.latest and version == sorted_versions[-1] and not existence:
                existence = image['name'] in cloud_images
                if existence:
                    existence = cloud_images[image['name']]['properties']['internal_version'] == version

            elif (image['multi'] and len(sorted_versions) > 1 and version == sorted_versions[-1]
                  and not existence):
                previous = "%s (%s)" % (image['name'], sorted_versions[-2])
                existence = previous in cloud_images and image['name'] in cloud_images

            elif (image['multi'] and len(sorted_versions) > 1 and version == sorted_versions[-2]
                  and not existence):
                existence = image['name'] in cloud_images

            elif image['multi'] and len(sorted_versions) == 1:
                existence = image['name'] in cloud_images

            if not existence and not (self.CONF.latest and len(sorted_versions) > 1 and version != sorted_versions[-1]):

                url = versions[version]['url']
                r = requests.head(url)

                if r.status_code in [200, 302]:
                    logging.info("Tested URL %s: %s" % (url, r.status_code))
                else:
                    logging.error("Tested URL %s: %s" % (url, r.status_code))
                    logging.error("Skipping '%s' due to HTTP status code %s" % (name, r.status_code))
                    self.exit_with_error = True
                    return existing_images, imported_image, previous_image

                if image['multi'] and image['name'] in cloud_images:
                    self.previous_image = cloud_images[image['name']]

                if not self.CONF.dry_run:
                    self.import_image(image, name, url)
                    logging.info("Import of '%s' successfully completed, reloading images" % name)
                    cloud_images = self.get_images()
                    imported_image = cloud_images[name]

            elif self.CONF.latest and version != sorted_versions[-1]:
                logging.info("Skipping image '%s' (only importing the latest version from type multi)" % name)

            if image['multi']:
                existing_images.add(image['name'])
            else:
                existing_images.add(name)

            if imported_image:
                self.set_properties(image, name, versions, version)
        return existing_images, imported_image, previous_image

    def set_properties(self, image: dict, name: str, versions: dict, version: str) -> None:
        '''
        Set image properties and tags based on the configuration from images.yml

        Params:
            image: image dict from images.yml
            name: name of the image including the version string
            versions: versions dict generated by main()
            version: currently processed version
        '''
        cloud_images = self.get_images()

        if name in cloud_images:
            logging.info("Checking parameters of '%s'" % name)

            cloud_image = cloud_images[name]
            real_image_size = int(Decimal(cloud_image.size / 2**30).quantize(Decimal('1.'), rounding=ROUND_UP))

            if 'min_disk' in image and image['min_disk'] != cloud_image.min_disk:
                logging.info("Setting min_disk: %s != %s" % (image['min_disk'], cloud_image.min_disk))
                self.conn.image.update_image(cloud_image.id, **{'min_disk': int(image['min_disk'])})

            if ('min_disk' in image and real_image_size > image['min_disk']) or 'min_disk' not in image:
                logging.info("Setting min_disk = %d" % real_image_size)
                self.conn.image.update_image(cloud_image.id, **{'min_disk': real_image_size})

            if 'min_ram' in image and image['min_ram'] != cloud_image.min_ram:
                logging.info("Setting min_ram: %s != %s" % (image['min_ram'], cloud_image.min_ram))
                self.conn.image.update_image(cloud_image.id, **{'min_ram': int(image['min_ram'])})

            if 'build_date' in versions[version]:
                logging.info("Setting image_build_date = %s" % versions[version]['build_date'])
                image['meta']['image_build_date'] = versions[version]['build_date']

            if self.CONF.use_os_hidden:
                if 'hidden' in versions[version]:
                    logging.info("Setting os_hidden = %s" % versions[version]['hidden'])
                    self.conn.image.update_image(cloud_image.id, **{'os_hidden': versions[version]['hidden']})

                elif version != natsorted(versions.keys())[-1:]:
                    logging.info("Setting os_hidden = True")
                    self.conn.image.update_image(cloud_image.id, **{'os_hidden': True})

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
                    self.conn.image.add_tag(cloud_image.id, tag)

            for tag in cloud_image.tags:
                if tag not in image['tags']:
                    logging.info("Deleting tag %s" % (tag))
                    self.conn.image.remove_tag(cloud_image.id, tag)

            properties = cloud_image.properties
            for property in properties:
                if property in image['meta']:
                    if image['meta'][property] != properties[property]:
                        logging.info("Setting property %s: %s != %s" %
                                     (property, properties[property], image['meta'][property]))
                        self.conn.image.update_image(cloud_image.id, **{property: str(image['meta'][property])})

                elif property not in ['self', 'schema', 'stores'] or not property.startswith('os_'):
                    # FIXME: handle deletion of properties
                    logging.debug("Deleting property %s" % (property))

            for property in image['meta']:
                if property not in properties:
                    logging.info("Setting property %s: %s" % (property, image['meta'][property]))
                    self.conn.image.update_image(cloud_image.id, **{property: str(image['meta'][property])})

            logging.info("Checking status of '%s'" % name)
            if cloud_image.status != image['status'] and image['status'] == 'deactivated':
                logging.info("Deactivating image '%s'" % name)
                self.conn.image.deactivate_image(cloud_image.id)

            elif cloud_image.status != image['status'] and image['status'] == 'active':
                logging.info("Reactivating image '%s'" % name)
                self.conn.image.reactivate_image(cloud_image.id)

            logging.info("Checking visibility of '%s'" % name)
            if 'visibility' in versions[version]:
                visibility = versions[version]['visibility']
            else:
                visibility = image['visibility']

            if cloud_image.visibility != visibility:
                logging.info("Setting visibility of '%s' to '%s'" % (name, visibility))
                self.conn.image.update_image(cloud_image.id, visibility=visibility)

    def rename_images(self, name: str, sorted_versions: list, imported_image: Image, previous_image: Image) -> None:
        '''
        Rename outdated images in Glance (only applies to images of type multi)

        Params:
            name: the name of the image from images.yml
            sorted_versions: list with all sorted image versions
            imported_image: the newly imported image
            previous_image: the previous latest image
        '''
        cloud_images = self.get_images()

        if len(sorted_versions) > 1:
            latest = "%s (%s)" % (name, sorted_versions[-1])
            previous_latest = "%s (%s)" % (name, sorted_versions[-2])

            if name in cloud_images and previous_latest not in cloud_images:
                logging.info("Renaming %s to %s" % (name, previous_latest))
                self.conn.image.update_image(cloud_images[name].id, name=previous_latest)

            if latest in cloud_images:
                logging.info("Renaming %s to %s" % (latest, name))
                self.conn.image.update_image(cloud_images[latest].id, name=name)

        elif len(sorted_versions) == 1 and name in cloud_images:
            previous_latest = "%s (%s)" % (name, previous_image['properties']['internal_version'])

            logging.info("Renaming old latest '%s' to '%s'" % (name, previous_latest))
            self.conn.image.update_image(previous_image.id, name=previous_latest)

            logging.info("Renaming imported image '%s' to '%s'" % (imported_image.name, name))
            self.conn.image.update_image(imported_image.id, name=name)

        elif len(sorted_versions) == 1:
            latest = "%s (%s)" % (name, sorted_versions[-1])

            if latest in cloud_images:
                logging.info("Renaming %s to %s" % (latest, name))
                self.conn.image.update_image(cloud_images[latest].id, name=name)

    def manage_outdated_images(self, managed_images: set) -> list:
        '''
        Delete, hide or deactivate outdated images

        Params:
            managed_images: set of managed images
        Raises:
            Exception: when the image is still in use and cannot be deleted
            Exception: when the image cannot be deactivated or its visibility cannot be changed
        Returns:
            List with all images that are unmanaged and get affected by this method
        '''
        cloud_images = self.get_images()
        unmanaged_images = [x for x in cloud_images if x not in managed_images]

        for image in unmanaged_images:
            cloud_image = cloud_images[image]
            if self.CONF.delete and self.CONF.yes_i_really_know_what_i_do:
                try:
                    logging.info("Deactivating image '%s'" % image)
                    self.conn.image.deactivate_image(cloud_image.id)

                    logging.info("Setting visibility of '%s' to 'community'" % image)
                    self.conn.image.update_image(cloud_image.id, visibility='community')

                    logging.info("Deleting %s" % image)
                    self.conn.image.delete_image(cloud_image.id)
                except Exception as e:
                    logging.info("%s is still in use and cannot be deleted\n %s" % (image, e))

            else:
                logging.warning("Image %s should be deleted" % image)
                try:
                    if self.CONF.deactivate:
                        logging.info("Deactivating image '%s'" % image)
                        self.conn.image.deactivate_image(cloud_image.id)

                    if self.CONF.hide:
                        cloud_image = cloud_images[image]
                        logging.info("Setting visibility of '%s' to 'community'" % image)
                        self.conn.image.update_image(cloud_image.id, visibility='community')
                except Exception as e:
                    logging.error('An Exception occurred: \n%s' % e)
                    self.exit_with_error = True
        return unmanaged_images


if __name__ == '__main__':
    image_manager = ImageManager()
    image_manager.create_cli_args()
    image_manager.main()
