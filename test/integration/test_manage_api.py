import openstack
from loguru import logger
from munch import Munch
from unittest import TestCase

from openstack_image_manager import manage

logger.remove()   # disable all logging from manage.py


class TestManageAPI(TestCase):

    def setUp(self):
        self.sot = manage.ImageManager()

        self.sot.CONF = Munch(
            latest=True,
            dry_run=False,
            use_os_hidden=False,
            delete=True,    # delete the image after the test
            yes_i_really_know_what_i_do=True,
            hide=False,
            deactivate=False,
            cloud='openstack',
            images='test/integration/fixtures/',
            tag='fake_tag',
            filter='',
            keep=False,
            force=False,
            hypervisor=None
        )
        self.web_image = self.sot.read_image_files()[0]
        self.assertEqual(self.web_image['name'], 'Cirros_test')
        self.web_image['tags'].append(self.sot.CONF.tag)
        self.web_image_name = self.web_image['name'] + ' (1)'

        self.file_image = self.sot.read_image_files()[1]
        self.assertEqual(self.file_image['name'], 'Cirros_test_file')
        self.file_image['tags'].append(self.sot.CONF.tag)
        self.file_image_name = self.file_image['name'] + ' (1)'

    def test_api_functions_for_web_download(self):
        '''
        Test all used API functions for web imports, as they appear in openstack_image_manager.manage.py
        Import the image via web-download, set its properties, rename it and delete it afterwards
        '''
        self.sot.conn = openstack.connect(cloud=self.sot.CONF.cloud)

        # make sure there are no images in the cloud already
        cloud_images = self.sot.get_images()
        self.assertEqual(cloud_images,
                         {},
                         f'Please make sure to delete any preexisting images with tag {self.sot.CONF.tag}')

        # test the image import
        imported_image = self.sot.import_image(self.web_image,
                                               self.web_image_name,
                                               self.web_image['versions'][0]['url'],
                                               {'1': self.web_image['versions'][0]},
                                               '1')
        self.assertEqual(imported_image.properties['os_glance_failed_import'], '')
        self.assertEqual(imported_image.visibility, 'private')
        self.assertEqual(imported_image.name, self.web_image_name)
        self.assertEqual(imported_image.min_ram, self.web_image['min_ram'])
        self.assertEqual(imported_image.min_disk, self.web_image['min_disk'])
        self.assertEqual(imported_image.tags, [self.sot.CONF.tag])
        self.assertEqual(imported_image.container_format, 'bare')
        self.assertEqual(imported_image.status, 'active')
        self.assertFalse(imported_image.is_hidden)

        # test set properties
        self.web_image['meta']['image_build_date'] = self.web_image['versions'][0]['build_date']
        self.sot.set_properties(self.web_image, self.web_image_name, {'1': self.web_image['versions'][0]}, '1', '', self.web_image['meta'])

        # assert the properties of the image got updated
        image = self.sot.get_images()[self.web_image_name]
        self.assertEqual(image.properties['os_glance_failed_import'], '')
        self.assertEqual(image.visibility, 'public')
        self.assertEqual(image.name, self.web_image_name)
        self.assertEqual(image.min_ram, self.web_image['min_ram'])
        self.assertEqual(image.min_disk, self.web_image['min_disk'])
        self.assertEqual(image.tags, [self.sot.CONF.tag])
        self.assertEqual(image.container_format, 'bare')
        self.assertEqual(image.status, 'active')
        self.assertEqual(image.architecture, self.web_image['meta']['architecture'])
        self.assertEqual(image.hw_disk_bus, self.web_image['meta']['hw_disk_bus'])
        self.assertEqual(image.hw_rng_model, self.web_image['meta']['hw_rng_model'])
        self.assertEqual(image.hw_scsi_model, self.web_image['meta']['hw_scsi_model'])
        self.assertEqual(image.hw_watchdog_action, self.web_image['meta']['hw_watchdog_action'])
        self.assertEqual(image.os_distro, self.web_image['meta']['os_distro'])
        self.assertEqual(image.os_version, self.web_image['meta']['os_version'])
        self.assertEqual(image.properties['image_original_user'], self.web_image['login'])
        self.assertEqual(image.properties['internal_version'], '1')
        self.assertEqual(image.properties['replace_frequency'], self.web_image['meta']['replace_frequency'])
        self.assertEqual(image.properties['uuid_validity'], self.web_image['meta']['uuid_validity'])
        self.assertEqual(image.properties['provided_until'], self.web_image['meta']['provided_until'])
        self.assertEqual(image.properties['image_build_date'], str(self.web_image['versions'][0]['build_date']))
        self.assertFalse(image.is_hidden)

        # test image rename
        self.sot.rename_images(self.web_image['name'], ['1'], None, None)

        # assert the image got renamed
        cloud_images = self.sot.get_images()
        self.assertEqual(list(cloud_images.keys()), [self.web_image['name']])

        # Make sure no images are considered unmanaged
        res = self.sot.manage_outdated_images({'Cirros_test'})
        self.assertEqual(res, [])

        # Manually delete the image
        self.sot.conn.image.delete_image(cloud_images['Cirros_test'].id)

        # make sure the image is gone
        cloud_images = self.sot.get_images()
        self.assertEqual(cloud_images, {}, f"Could not delete image {self.web_image['name']}, please do so manually")

    def test_api_functions_for_file_upload(self):
        '''
        Test all used API functions for file uploads, as they appear in openstack_image_manager.manage.py
        Import the image via local file upload, set its properties, rename it and delete it afterwards
        '''
        self.sot.conn = openstack.connect(cloud=self.sot.CONF.cloud)

        # make sure there are no images in the cloud already
        cloud_images = self.sot.get_images()
        self.assertEqual(cloud_images,
                         {},
                         f'Please make sure to delete any preexisting images with tag {self.sot.CONF.tag}')

        # test the image import
        imported_image = self.sot.import_image(self.file_image,
                                               self.file_image_name,
                                               self.file_image['versions'][0]['url'],
                                               {'1': self.file_image['versions'][0]},
                                               '1')
        self.assertEqual(imported_image.properties['os_glance_failed_import'], '')
        self.assertEqual(imported_image.visibility, 'private')
        self.assertEqual(imported_image.name, self.file_image_name)
        self.assertEqual(imported_image.min_ram, self.file_image['min_ram'])
        self.assertEqual(imported_image.min_disk, self.file_image['min_disk'])
        self.assertEqual(imported_image.tags, [self.sot.CONF.tag])
        self.assertEqual(imported_image.container_format, 'bare')
        self.assertEqual(imported_image.status, 'active')
        self.assertFalse(imported_image.is_hidden)

        # test set properties
        self.file_image['meta']['image_build_date'] = self.file_image['versions'][0]['build_date']
        self.sot.set_properties(self.file_image, self.file_image_name, {'1': self.file_image['versions'][0]}, '1', '', self.file_image['meta'])

        # assert the properties of the image got updated
        image = self.sot.get_images()[self.file_image_name]
        self.assertEqual(image.properties['os_glance_failed_import'], '')
        self.assertEqual(image.visibility, 'public')
        self.assertEqual(image.name, self.file_image_name)
        self.assertEqual(image.min_ram, self.file_image['min_ram'])
        self.assertEqual(image.min_disk, self.file_image['min_disk'])
        self.assertEqual(image.tags, [self.sot.CONF.tag])
        self.assertEqual(image.container_format, 'bare')
        self.assertEqual(image.status, 'active')
        self.assertEqual(image.architecture, self.file_image['meta']['architecture'])
        self.assertEqual(image.hw_disk_bus, self.file_image['meta']['hw_disk_bus'])
        self.assertEqual(image.hw_rng_model, self.file_image['meta']['hw_rng_model'])
        self.assertEqual(image.hw_scsi_model, self.file_image['meta']['hw_scsi_model'])
        self.assertEqual(image.hw_watchdog_action, self.file_image['meta']['hw_watchdog_action'])
        self.assertEqual(image.os_distro, self.file_image['meta']['os_distro'])
        self.assertEqual(image.os_version, self.file_image['meta']['os_version'])
        self.assertEqual(image.properties['image_original_user'], self.file_image['login'])
        self.assertEqual(image.properties['internal_version'], '1')
        self.assertEqual(image.properties['replace_frequency'], self.file_image['meta']['replace_frequency'])
        self.assertEqual(image.properties['uuid_validity'], self.file_image['meta']['uuid_validity'])
        self.assertEqual(image.properties['provided_until'], self.file_image['meta']['provided_until'])
        self.assertEqual(image.properties['image_build_date'], str(self.file_image['versions'][0]['build_date']))
        self.assertFalse(image.is_hidden)

        # test image rename
        self.sot.rename_images(self.file_image['name'], ['1'], None, None)

        # assert the image got renamed
        cloud_images = self.sot.get_images()
        self.assertEqual(list(cloud_images.keys()), [self.file_image['name']])

        # Make sure no images are considered unmanaged
        res = self.sot.manage_outdated_images({'Cirros_test_file'})
        self.assertEqual(res, [])

        # Manually delete the image
        self.sot.conn.image.delete_image(cloud_images['Cirros_test_file'].id)

        # make sure the image is gone
        cloud_images = self.sot.get_images()
        self.assertEqual(cloud_images, {}, f"Could not delete image {self.file_image['name']}, please do so manually")
