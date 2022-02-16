import logging
from munch import Munch
from unittest import TestCase, mock
from openstack.image.v2.image import Image
from openstack.image.v2._proxy import Proxy

from src import manage

logging.disable(logging.CRITICAL)   # disable all logging from manage.py

# sample config from images.yml
FAKE_YML = '''
---
images:
  - name: Ubuntu 20.04
    format: qcow2
    login: ubuntu
    min_disk: 8
    min_ram: 512
    status: active
    visibility: public
    multi: true
    meta:
      os_distro: ubuntu
      os_version: '20.04'
    tags: []
    versions:
      - version: '1'
        url: https://url.com
        checksum: "1234"
'''

# sample image dict as generated from FAKE_YML
FAKE_IMAGE_DICT = {
    'name': 'Ubuntu 20.04',
    'format': 'qcow2',
    'login': 'ubuntu',
    'min_disk': 8,
    'min_ram': 512,
    'status': 'active',
    'visibility': 'public',
    'multi': True,
    'meta': {
        'os_distro': 'ubuntu',
        'os_version': '20.04'
    },
    'tags': [],
    'versions': [
        {
            'version': '1',
            'url': 'https://url.com',
            'checksum': '1234'
        }
    ]
}

# data to generate a fake openstack.image.v2.image.Image object
FAKE_IMAGE_DATA = {
    'id': '123456789abcdef',
    'name': FAKE_IMAGE_DICT['name'],
    'container_format': 'bare',
    'disk_format': FAKE_IMAGE_DICT['format'],
    'min_disk': FAKE_IMAGE_DICT.get('min_disk', 0),
    'min_ram': FAKE_IMAGE_DICT.get('min_ram', 0),
    'size': 123456789,
    'protected': False,
    'status': 'active',
    'tags': ['fake_tag'],
    'os_hidden': False,
    'visibility': 'public',
    'os_distro': FAKE_IMAGE_DICT['meta']['os_distro'],
    'os_version': FAKE_IMAGE_DICT['meta']['os_version'],
    'properties': {
        'image_original_user': FAKE_IMAGE_DICT['login'],
        'internal_version': FAKE_IMAGE_DICT['versions'][0]['version']
    }
}


class TestManage(TestCase):

    def setUp(self):
        ''' create all necessary test data, gets called before each test '''

        # since oslo_config.cfg.ConfigOpts objects allow attribute-style access,
        # we can mimick its behaviour with a munch.Munch object
        self.fake_CONF = Munch(
            latest=True,
            dry_run=False,
            use_os_hidden=False,
            delete=False,
            yes_i_really_know_what_i_do=False,
            hide=False,
            deactivate=False,
            cloud='fake-cloud',
            images='fake.yml',
            name=None,
            tag='fake_tag'
        )
        # we can also mimick an openstack connection object with a Munch
        self.conn = Munch(
            current_project_id='123456789',
            image=Proxy
        )
        self.fake_image_dict = FAKE_IMAGE_DICT
        self.fake_image = Image(**FAKE_IMAGE_DATA)
        self.fake_name = '%s (%s)' % (self.fake_image_dict['name'], 1)
        self.fake_url = 'http://sample-url.com'

    def tearDown(self):
        pass

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.images')
    def test_get_images(self, mock_images):
        ''' test manage.get_images() '''

        mock_images.return_value = [self.fake_image]

        result = manage.get_images(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_images.assert_called_once()
        self.assertEqual(result, {self.fake_image.name: self.fake_image})

        mock_images.reset_mock()

        # test with use_os_hidden = True
        result = manage.get_images(self.conn, self.fake_CONF.tag, use_os_hidden=True)
        mock_images.assert_called_with(**{'os_hidden': True})
        self.assertEqual(mock_images.call_count, 2)
        self.assertEqual(result, {self.fake_image.name: self.fake_image})

    @mock.patch('src.manage.time.sleep', side_effect=InterruptedError)
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.get_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.import_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.create_image')
    def test_import_image(self, mock_create, mock_import, mock_get_image, mock_sleep):
        ''' test manage.import_image() '''

        mock_create.return_value = self.fake_image
        properties = {
            'container_format': 'bare',
            'disk_format': self.fake_image_dict['format'],
            'min_disk': self.fake_image_dict.get('min_disk', 0),
            'min_ram': self.fake_image_dict.get('min_ram', 0),
            'name': self.fake_name,
            'tags': [self.fake_CONF.tag],
            'visibility': 'private'
        }

        manage.import_image(self.conn, self.fake_name, self.fake_image_dict, self.fake_url, self.fake_CONF.tag)

        mock_create.assert_called_once_with(**properties)
        mock_import.assert_called_once_with(self.fake_image, method='web-download', uri=self.fake_url)
        mock_get_image.assert_called_once_with(self.fake_image)
        mock_sleep.assert_called_once_with(10.0)

    @mock.patch('src.manage.set_properties')
    @mock.patch('src.manage.import_image')
    @mock.patch('src.manage.requests.head')
    @mock.patch('src.manage.get_images')
    def test_process_image(self, mock_get_images, mock_requests, mock_import_image, mock_set_properties):
        ''' test manage.process_image() '''

        versions = {1: {'url': self.fake_url}}
        mock_requests.return_value.status_code = 200

        result = manage.process_image(self.conn, self.fake_image_dict, versions, [1], self.fake_CONF)

        mock_get_images.assert_called_with(self.conn, self.fake_CONF.tag, False)
        self.assertEqual(mock_get_images.call_count, 2)
        mock_requests.assert_called_once_with(self.fake_url)
        mock_import_image.assert_called_once_with(self.conn,
                                                  self.fake_name,
                                                  self.fake_image_dict,
                                                  self.fake_url,
                                                  self.fake_CONF.tag)
        mock_set_properties.assert_called_once_with(self.conn,
                                                    self.fake_image_dict,
                                                    self.fake_name,
                                                    versions,
                                                    1,
                                                    self.fake_CONF)
        self.assertEqual(result, (True, None, mock_get_images().__getitem__(), {self.fake_image_dict['name']}))

        mock_get_images.reset_mock()
        mock_requests.reset_mock()
        mock_import_image.reset_mock()
        mock_set_properties.reset_mock()

        # test the same function with dry_run = True
        self.fake_CONF.dry_run = True
        result = manage.process_image(self.conn, self.fake_image_dict, versions, [1], self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, False)
        mock_requests.assert_called_once_with(self.fake_url)
        mock_import_image.assert_not_called()
        mock_set_properties.assert_not_called()
        self.assertEqual(result, (False, None, None, {self.fake_image_dict['name']}))

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.deactivate_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.remove_tag')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.add_tag')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.update_image')
    @mock.patch('src.manage.get_images')
    def test_set_properties(self, mock_get_images, mock_update_image, mock_add_tag, mock_remove_tag, mock_deactivate):
        ''' test manage.set_properties() '''

        versions = {'1': {}}
        mock_get_images.return_value = {
            self.fake_name: self.fake_image
        }

        self.fake_image_dict['tags'] = ['my_tag']
        self.fake_image_dict['status'] = 'deactivated'

        manage.set_properties(self.conn, self.fake_image_dict, self.fake_name, versions, '1', self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_update_image.assert_called()
        mock_add_tag.assert_called_once_with(self.fake_image.id, 'my_tag')
        mock_remove_tag.assert_called_once_with(self.fake_image.id, 'fake_tag')
        mock_deactivate.assert_called_once_with(self.fake_image.id)

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.update_image')
    @mock.patch('src.manage.get_images')
    def test_rename_images(self, mock_get_images, mock_update_image):
        ''' test manage.rename_images() '''

        # test with len(sorted_versions) > 1
        mock_get_images.return_value = {
            self.fake_name: self.fake_image,
            self.fake_image.name: self.fake_image
        }

        manage.rename_images(self.conn, self.fake_image.name, [2, 1], self.fake_image, self.fake_image, self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)
        self.assertEqual(mock_update_image.call_count, 2)

        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1 and name in cloud_images
        mock_get_images.return_value = {
            self.fake_image.name: self.fake_image
        }

        manage.rename_images(self.conn, self.fake_image.name, [1], self.fake_image, self.fake_image, self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)
        self.assertEqual(mock_update_image.call_count, 2)

        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1
        mock_get_images.return_value = {
            self.fake_name: self.fake_image
        }

        manage.rename_images(self.conn, self.fake_image.name, [1], self.fake_image, self.fake_image, self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_update_image.assert_called_once_with(self.fake_image.id, name=mock.ANY)

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.delete_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.update_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.deactivate_image')
    @mock.patch('src.manage.get_images')
    def test_manage_outdated_images(self, mock_get_images, mock_deactivate, mock_update_image, mock_delete_image):
        ''' test manage.manage_outdated_images '''

        # test deletion of images
        self.fake_CONF.delete = True
        self.fake_CONF.yes_i_really_know_what_i_do = True
        managed_images = {'some_image_name'}
        mock_get_images.return_value = {
            self.fake_image.name: self.fake_image
        }

        manage.manage_outdated_images(self.conn, managed_images, self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_deactivate.assert_called_once_with(self.fake_image.id)
        mock_update_image.assert_called_once_with(self.fake_image.id, visibility='community')
        mock_delete_image.assert_called_once_with(self.fake_image.id)

        mock_get_images.reset_mock()
        mock_deactivate.reset_mock()
        mock_update_image.reset_mock()
        mock_delete_image.reset_mock()

        # test hide and deactivate of images
        self.fake_CONF.delete = False
        self.fake_CONF.yes_i_really_know_what_i_do = False
        self.fake_CONF.hide = True
        self.fake_CONF.deactivate = True
        manage.manage_outdated_images(self.conn, managed_images, self.fake_CONF)

        mock_get_images.assert_called_once_with(self.conn, self.fake_CONF.tag, self.fake_CONF.use_os_hidden)
        mock_deactivate.assert_called_once_with(self.fake_image.id)
        mock_update_image.assert_called_once_with(self.fake_image.id, visibility='community')
        mock_delete_image.assert_not_called()

    @mock.patch('src.manage.manage_outdated_images')
    @mock.patch('src.manage.rename_images')
    @mock.patch('src.manage.process_image')
    @mock.patch('src.manage.openstack.connect')
    @mock.patch('builtins.open', mock.mock_open(read_data=str(FAKE_YML)))
    def test_main(self, mock_connect, mock_process_image, mock_rename_images, mock_manage_outdated):
        ''' test manage.main() '''

        self.fake_image_dict['tags'] = [self.fake_CONF.tag, 'os:ubuntu']
        versions = {'1': {'url': 'https://url.com'}}
        mock_connect.return_value = self.conn
        mock_process_image.return_value = (True, Image(), Image(), {self.fake_image_dict['name']})

        manage.main(self.fake_CONF)

        mock_connect.assert_called_once_with(cloud=self.fake_CONF.cloud)
        mock_process_image.assert_called_once_with(self.conn, self.fake_image_dict, versions, ['1'], self.fake_CONF)
        mock_rename_images.assert_called_once_with(self.conn,
                                                   self.fake_image_dict['name'],
                                                   ['1'],
                                                   Image(),
                                                   Image(),
                                                   self.fake_CONF)
        mock_manage_outdated.assert_called_once_with(self.conn, {self.fake_image_dict['name']}, self.fake_CONF)

        mock_connect.reset_mock()
        mock_process_image.reset_mock()
        mock_rename_images.reset_mock()
        mock_manage_outdated.reset_mock()

        # test with dry_run = True
        self.fake_CONF.dry_run = True
        mock_process_image.return_value = (False, None, None, {self.fake_image_dict['name']})

        manage.main(self.fake_CONF)

        mock_connect.assert_called_once_with(cloud=self.fake_CONF.cloud)
        mock_process_image.assert_called_once_with(self.conn, self.fake_image_dict, versions, ['1'], self.fake_CONF)
        mock_rename_images.assert_not_called()
        mock_manage_outdated.assert_not_called()
