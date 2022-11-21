from loguru import logger
from munch import Munch
from unittest import TestCase, mock
from openstack.image.v2.image import Image
from openstack.image.v2._proxy import Proxy

from src import manage

logger.remove()   # disable all logging from manage.py

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
      image_description: Ubuntu 20.04
      os_distro: ubuntu
      os_version: '20.04'
    tags: []
    versions:
      - version: '1'
        url: http://url.com
        checksum: '1234'
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
        'image_description': 'Ubuntu 20.04',
        'os_distro': 'ubuntu',
        'os_version': '20.04'
    },
    'tags': [],
    'versions': [
        {
            'version': '1',
            'url': 'http://url.com',
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

        self.fake_image_dict = FAKE_IMAGE_DICT.copy()
        self.fake_image = Image(**FAKE_IMAGE_DATA)
        self.fake_name = '%s (%s)' % (self.fake_image_dict['name'], '1')
        self.fake_url = 'http://url.com'
        self.versions = {'1': {'url': self.fake_url, 'meta': {'image_source': self.fake_url}}}
        self.sorted_versions = ['2', '1']
        self.previous_image = self.fake_image
        self.imported_image = self.fake_image

        self.sot = manage.ImageManager()
        # since oslo_config.cfg.ConfigOpts objects allow attribute-style access,
        # we can mimick its behaviour with a munch.Munch object
        self.sot.CONF = Munch(
            latest=True,
            dry_run=False,
            use_os_hidden=False,
            delete=False,
            yes_i_really_know_what_i_do=False,
            hide=False,
            deactivate=False,
            cloud='fake-cloud',
            images='etc/images/',
            name=None,
            tag='fake_tag',
            filter='',
            check=False,
            validate=False
        )

        # we can also mimick an openstack connection object with a Munch
        self.sot.conn = Munch(
            current_project_id='123456789',
            image=Proxy
        )

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.images')
    def test_get_images(self, mock_images):
        ''' test manage.ImageManager.get_images() '''

        mock_images.return_value = [self.fake_image]
        expected_result = {self.fake_image.name: self.fake_image}

        result = self.sot.get_images()
        mock_images.assert_called_once()
        self.assertEqual(result, expected_result)

        mock_images.reset_mock()

        # test with use_os_hidden = True
        self.sot.CONF.use_os_hidden = True
        result = self.sot.get_images()
        mock_images.assert_called_with(**{'os_hidden': True})
        self.assertEqual(mock_images.call_count, 2)
        self.assertEqual(result, expected_result)

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.get_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.import_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.create_image')
    def test_import_image(self, mock_create, mock_import, mock_get_image):
        ''' test manage.ImageManager.import_image() '''

        mock_create.return_value = self.fake_image
        mock_get_image.return_value = self.fake_image
        properties = {
            'container_format': 'bare',
            'disk_format': self.fake_image_dict['format'],
            'min_disk': self.fake_image_dict.get('min_disk', 0),
            'min_ram': self.fake_image_dict.get('min_ram', 0),
            'name': self.fake_name,
            'tags': [self.sot.CONF.tag],
            'visibility': 'private'
        }

        self.sot.import_image(self.fake_image_dict, self.fake_name, self.fake_url, self.versions, '1')

        mock_create.assert_called_once_with(**properties)
        mock_import.assert_called_once_with(self.fake_image, method='web-download', uri=self.fake_url)
        mock_get_image.assert_called_once_with(self.fake_image)

    @mock.patch('src.manage.ImageManager.set_properties')
    @mock.patch('src.manage.ImageManager.import_image')
    @mock.patch('src.manage.requests.head')
    @mock.patch('src.manage.ImageManager.get_images')
    def test_process_image(self, mock_get_images, mock_requests, mock_import_image, mock_set_properties):
        ''' test manage.ImageManager.process_image() '''

        mock_requests.return_value.status_code = 200
        meta = self.fake_image_dict['meta']

        result = self.sot.process_image(self.fake_image_dict, self.versions, self.sorted_versions, meta)

        self.assertEqual(mock_get_images.call_count, 2)
        mock_requests.assert_called_once_with(self.fake_url)
        mock_import_image.assert_called_once_with(self.fake_image_dict,
                                                  self.fake_name,
                                                  self.fake_url,
                                                  self.versions,
                                                  '1')
        mock_set_properties.assert_called_once_with(self.fake_image_dict, self.fake_name, self.versions, '1', '', meta)
        self.assertEqual(result, ({self.fake_image_dict['name']}, mock_get_images.return_value.__getitem__(), None))

        mock_get_images.reset_mock()
        mock_requests.reset_mock()
        mock_import_image.reset_mock()
        mock_set_properties.reset_mock()

        # test the same function with dry_run = True
        self.sot.CONF.dry_run = True
        result = self.sot.process_image(self.fake_image_dict, self.versions, self.sorted_versions, meta)

        mock_get_images.assert_called_once()
        mock_requests.assert_called_once_with(self.fake_url)
        mock_import_image.assert_not_called()
        mock_set_properties.assert_not_called()
        self.assertEqual(result, ({self.fake_image_dict['name']}, None, None))

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.deactivate_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.remove_tag')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.add_tag')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.update_image')
    @mock.patch('src.manage.ImageManager.get_images')
    def test_set_properties(self, mock_get_images, mock_update_image, mock_add_tag, mock_remove_tag, mock_deactivate):
        ''' test manage.ImageManager.set_properties() '''

        meta = self.fake_image_dict['meta']
        mock_get_images.return_value = {self.fake_name: self.fake_image}

        self.fake_image_dict['tags'] = ['my_tag']
        self.fake_image_dict['status'] = 'deactivated'

        self.sot.set_properties(self.fake_image_dict, self.fake_name, self.versions, '1', '', meta)

        mock_get_images.assert_called_once()
        mock_update_image.assert_called()
        mock_add_tag.assert_called_once_with(self.fake_image.id, 'my_tag')
        mock_remove_tag.assert_called_once_with(self.fake_image.id, 'fake_tag')
        mock_deactivate.assert_called_once_with(self.fake_image.id)

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.update_image')
    @mock.patch('src.manage.ImageManager.get_images')
    def test_rename_images(self, mock_get_images, mock_update_image):
        ''' test manage.ImageManager.rename_images() '''

        # test with len(sorted_versions) > 1
        mock_get_images.return_value = {
            self.fake_name: self.fake_image,
            self.fake_image.name: self.fake_image
        }
        self.sot.rename_images(self.fake_image.name, self.sorted_versions, self.imported_image, self.previous_image)

        mock_get_images.assert_called_once()
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)

        self.assertEqual(mock_update_image.call_count, 2)
        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1 and name in cloud_images
        mock_get_images.return_value = {self.fake_image.name: self.fake_image}
        self.sorted_versions = ['1']

        self.sot.rename_images(self.fake_image.name, self.sorted_versions, self.imported_image, self.previous_image)
        mock_get_images.assert_called_once()
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)
        self.assertEqual(mock_update_image.call_count, 2)

        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1
        mock_get_images.return_value = {self.fake_name: self.fake_image}

        self.sot.rename_images(self.fake_image.name, self.sorted_versions, self.imported_image, self.previous_image)
        mock_get_images.assert_called_once()
        mock_update_image.assert_called_once_with(self.fake_image.id, name=mock.ANY)

    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.delete_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.update_image')
    @mock.patch('src.manage.openstack.image.v2._proxy.Proxy.deactivate_image')
    @mock.patch('src.manage.ImageManager.get_images')
    def test_manage_outdated_images(self, mock_get_images, mock_deactivate, mock_update_image, mock_delete_image):
        ''' test manage.ImageManager.manage_outdated_images '''

        # test deletion of images
        self.sot.CONF.delete = True
        self.sot.CONF.yes_i_really_know_what_i_do = True
        managed_images = {'some_image_name'}
        mock_get_images.return_value = {
            self.fake_image.name: self.fake_image
        }

        self.sot.manage_outdated_images(managed_images)
        mock_get_images.assert_called_once()
        mock_deactivate.assert_called_once_with(self.fake_image.id)
        mock_update_image.assert_called_once_with(self.fake_image.id, visibility='community')
        mock_delete_image.assert_called_once_with(self.fake_image.id)

        mock_get_images.reset_mock()
        mock_deactivate.reset_mock()
        mock_update_image.reset_mock()
        mock_delete_image.reset_mock()

        # test hide and deactivate of images
        self.sot.CONF.delete = False
        self.sot.CONF.yes_i_really_know_what_i_do = False
        self.sot.CONF.hide = True
        self.sot.CONF.deactivate = True

        self.sot.manage_outdated_images(managed_images)
        mock_get_images.assert_called_once()
        mock_deactivate.assert_called_once_with(self.fake_image.id)
        mock_update_image.assert_called_once_with(self.fake_image.id, visibility='community')
        mock_delete_image.assert_not_called()

    @mock.patch('src.manage.ImageManager.validate_yaml_schema')
    @mock.patch('src.manage.ImageManager.check_image_metadata')
    @mock.patch('src.manage.ImageManager.manage_outdated_images')
    @mock.patch('src.manage.ImageManager.process_images')
    @mock.patch('src.manage.ImageManager.get_images')
    @mock.patch('src.manage.ImageManager.read_image_files')
    @mock.patch('src.manage.openstack.connect')
    def test_main(self, mock_connect, mock_read_image_files, mock_get_images,
                  mock_process_images, mock_manage_outdated, mock_check_metadata, mock_validate_yaml):
        ''' test manage.ImageManager.main() '''
        mock_read_image_files.return_value = [self.fake_image_dict]

        self.sot.main()

        mock_connect.assert_called_once_with(cloud=self.sot.CONF.cloud)
        mock_read_image_files.assert_called_once()
        mock_get_images.assert_called_once()
        mock_process_images.assert_called_once_with([self.fake_image_dict])
        mock_manage_outdated.assert_called_once_with(set())
        mock_check_metadata.assert_not_called()
        mock_validate_yaml.assert_not_called()

        # reset
        mock_read_image_files.reset_mock()
        mock_get_images.reset_mock()
        mock_process_images.reset_mock()
        mock_manage_outdated.reset_mock()
        mock_check_metadata.reset_mock()
        mock_validate_yaml.reset_mock()

        # test with dry_run = True and validate = True
        self.sot.CONF.dry_run = True
        self.sot.CONF.validate = True

        self.sot.main()
        mock_read_image_files.assert_not_called()
        mock_get_images.assert_not_called()
        mock_process_images.assert_not_called()
        mock_manage_outdated.assert_not_called()
        mock_check_metadata.assert_called_once()
        mock_validate_yaml.assert_not_called()

        # reset
        mock_read_image_files.reset_mock()
        mock_get_images.reset_mock()
        mock_process_images.reset_mock()
        mock_manage_outdated.reset_mock()
        mock_check_metadata.reset_mock()
        mock_validate_yaml.reset_mock()

        # test with check = True
        self.sot.CONF.check = True

        self.sot.CONF.dry_run = False
        self.sot.CONF.validate = False

        self.sot.main()
        mock_read_image_files.assert_not_called()
        mock_get_images.assert_not_called()
        mock_process_images.assert_not_called()
        mock_manage_outdated.assert_not_called()
        mock_check_metadata.assert_not_called()
        mock_validate_yaml.assert_called_once()

    @mock.patch('src.manage.os.path.isfile')
    @mock.patch('src.manage.os.listdir')
    @mock.patch('builtins.open', mock.mock_open(read_data=str(FAKE_YML)))
    def test_read_image_files(self, mock_listdir, mock_isfile):
        ''' test manage.ImageManager.read_image_files() '''
        mock_listdir.return_value = ['fake.yml']
        mock_isfile.return_value = True

        result = self.sot.read_image_files()
        self.assertEqual(result, [FAKE_IMAGE_DICT])

    @mock.patch('src.manage.ImageManager.rename_images')
    @mock.patch('src.manage.ImageManager.process_image')
    def test_process_images(self, mock_process_image, mock_rename_images):
        ''' test manage.ImageManager.process_images() '''
        meta = self.fake_image_dict['meta']
        self.fake_image_dict['tags'] = [self.sot.CONF.tag, 'os:%s' % self.fake_image_dict['meta']['os_distro']]
        mock_process_image.return_value = ({self.fake_image_dict['name']}, self.imported_image, self.previous_image)

        result = self.sot.process_images([self.fake_image_dict])

        mock_process_image.assert_called_once_with(self.fake_image_dict, self.versions, ['1'], meta)
        mock_rename_images.assert_called_once_with(self.fake_image_dict['name'], ['1'],
                                                   self.imported_image,
                                                   self.previous_image)

        self.assertEqual(result, {self.fake_image_dict["name"]})
