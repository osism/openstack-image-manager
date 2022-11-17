import openstack
from loguru import logger
from munch import Munch
from unittest import TestCase

from src import manage

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
            name=None,
            tag='fake_tag',
            filter='',
            validate=False
        )
        self.image = self.sot.read_image_files()[0]
        self.assertEqual(self.image['name'], 'Cirros_test')
        self.image['tags'].append(self.sot.CONF.tag)
        self.name = self.image['name'] + ' (1)'

    def test_api_functions(self):
        '''
        Test all used API functions, as they appear in src.manage.py
        Import the image, set its properties, rename it and delete it afterwards
        '''
        self.sot.conn = openstack.connect(cloud=self.sot.CONF.cloud)

        # make sure there are no images in the cloud already
        cloud_images = self.sot.get_images()
        self.assertEqual(cloud_images,
                         {},
                         f'Please make sure to delete any preexisting images with tag {self.sot.CONF.tag}')

        # test the image import
        imported_image = self.sot.import_image(self.image,
                                               self.name,
                                               self.image['versions'][0]['url'],
                                               {'1': self.image['versions'][0]},
                                               '1')
        self.assertEqual(imported_image.properties['os_glance_failed_import'], '')
        self.assertEqual(imported_image.visibility, 'private')
        self.assertEqual(imported_image.name, self.name)
        self.assertEqual(imported_image.min_ram, self.image['min_ram'])
        self.assertEqual(imported_image.min_disk, self.image['min_disk'])
        self.assertEqual(imported_image.tags, [self.sot.CONF.tag])
        self.assertEqual(imported_image.container_format, 'bare')
        self.assertEqual(imported_image.status, 'active')
        self.assertFalse(imported_image.is_hidden)

        # test set properties
        self.image['meta']['image_build_date'] = self.image['versions'][0]['build_date']
        self.sot.set_properties(self.image, self.name, {'1': self.image['versions'][0]}, '1', '', self.image['meta'])

        # assert the properties of the image got updated
        image = self.sot.get_images()[self.name]
        self.assertEqual(image.properties['os_glance_failed_import'], '')
        self.assertEqual(image.visibility, 'public')
        self.assertEqual(image.name, self.name)
        self.assertEqual(image.min_ram, self.image['min_ram'])
        self.assertEqual(image.min_disk, self.image['min_disk'])
        self.assertEqual(image.tags, [self.sot.CONF.tag])
        self.assertEqual(image.container_format, 'bare')
        self.assertEqual(image.status, 'active')
        self.assertEqual(image.architecture, self.image['meta']['architecture'])
        self.assertEqual(image.hw_disk_bus, self.image['meta']['hw_disk_bus'])
        self.assertEqual(image.hw_rng_model, self.image['meta']['hw_rng_model'])
        self.assertEqual(image.hw_scsi_model, self.image['meta']['hw_scsi_model'])
        self.assertEqual(image.hw_watchdog_action, self.image['meta']['hw_watchdog_action'])
        self.assertEqual(image.os_distro, self.image['meta']['os_distro'])
        self.assertEqual(image.os_version, self.image['meta']['os_version'])
        self.assertEqual(image.properties['image_original_user'], self.image['login'])
        self.assertEqual(image.properties['internal_version'], '1')
        self.assertEqual(image.properties['replace_frequency'], self.image['meta']['replace_frequency'])
        self.assertEqual(image.properties['uuid_validity'], self.image['meta']['uuid_validity'])
        self.assertEqual(image.properties['provided_until'], self.image['meta']['provided_until'])
        self.assertEqual(image.properties['image_build_date'], str(self.image['versions'][0]['build_date']))
        self.assertFalse(image.is_hidden)

        # test image rename
        self.sot.rename_images(self.image['name'], ['1'], None, None)

        # assert the image got renamed
        cloud_images = self.sot.get_images()
        self.assertEqual(list(cloud_images.keys()), [self.image['name']])

        # Finally delete the image, also works as a cleanup
        res = self.sot.manage_outdated_images(set())
        self.assertEqual(res, [self.image['name']])

        # make sure the image is gone
        cloud_images = self.sot.get_images()
        self.assertEqual(cloud_images, {}, f"Cloud not delete image {self.image['name']}, please do so manually")
