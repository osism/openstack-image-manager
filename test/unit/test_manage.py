# SPDX-License-Identifier: Apache-2.0

import copy
import requests
import yamale
import yaml
from loguru import logger
from munch import Munch
from unittest import TestCase, mock
from openstack.image.v2.image import Image
from openstack.image.v2._proxy import Proxy
from typing import Any, Dict
from datetime import date
from openstack_image_manager import main
from yamale import YamaleError

logger.remove()  # disable all logging from main.py

# sample digests of all four supported lengths
MD5 = "9e107d9d372bb6826bd81d3542a419d6"
SHA1 = "2fd4e1c67a2d28fced849ee1bb76e7391b93eb12"
SHA256 = "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592"
SHA512 = (
    "07e547d9586f6a73f73fbac0435ed76951218fb7d0c8d788a309d785436bbb64"
    "2e93a252a954f23912547d1e8a3b5ed6e1bfd7097821233fa0538f3db854fee6"
)

# minimal image definition that passes the schema, used to probe
# individual schema fields
SCHEMA_TEST_IMAGE_DICT: Dict[str, Any] = {
    "name": "Test",
    "enable": True,
    "format": "qcow2",
    "login": "test",
    "min_disk": 8,
    "min_ram": 512,
    "status": "active",
    "visibility": "public",
    "multi": True,
    "meta": {
        "architecture": "x86_64",
        "hw_disk_bus": "virtio",
        "hypervisor_type": "qemu",
        "os_distro": "ubuntu",
        "os_purpose": "generic",
        "provided_until": "none",
        "replace_frequency": "never",
        "uuid_validity": "none",
    },
    "tags": [],
    "versions": [
        {
            "version": "latest",
            "build_date": date(2026, 1, 1),
            "url": "https://url.com/image.qcow2",
        }
    ],
}

# sample config from images.yml
FAKE_YML = """
---
images:
  - name: Ubuntu 20.04
    enable: True
    format: qcow2
    login: ubuntu
    min_disk: 8
    min_ram: 512
    status: active
    visibility: public
    multi: true
    meta:
      image_build_date: '2021-01-01'
      image_description: Ubuntu 20.04
      os_distro: ubuntu
      os_version: '20.04'
    tags: []
    versions:
      - version: '1'
        build_date: 2021-01-21
        url: http://url.com
        checksum: '1234'
"""

# sample image dict as generated from FAKE_YML
FAKE_IMAGE_DICT: Dict[str, Any] = {
    "name": "Ubuntu 20.04",
    "enable": True,
    "format": "qcow2",
    "login": "ubuntu",
    "min_disk": 8,
    "min_ram": 512,
    "status": "active",
    "visibility": "public",
    "multi": True,
    "meta": {
        "image_build_date": "2021-01-01",
        "image_description": "Ubuntu 20.04",
        "os_distro": "ubuntu",
        "os_version": "20.04",
    },
    "tags": [],
    "versions": [
        {
            "build_date": date.fromisoformat("2021-01-21"),
            "version": "1",
            "url": "http://url.com",
            "checksum": "1234",
        }
    ],
}

# data to generate a fake openstack.image.v2.image.Image object
FAKE_IMAGE_DATA = {
    "id": "123456789abcdef",
    "name": FAKE_IMAGE_DICT["name"],
    "container_format": "bare",
    "disk_format": FAKE_IMAGE_DICT["format"],
    "min_disk": FAKE_IMAGE_DICT.get("min_disk", 0),
    "min_ram": FAKE_IMAGE_DICT.get("min_ram", 0),
    "size": 123456789,
    "protected": False,
    "status": "active",
    "tags": ["fake_tag"],
    "os_hidden": False,
    "visibility": "public",
    "os_distro": FAKE_IMAGE_DICT["meta"]["os_distro"],
    "os_version": FAKE_IMAGE_DICT["meta"]["os_version"],
    "properties": {
        "image_build_date": "2021-01-01",
        "image_original_user": FAKE_IMAGE_DICT["login"],
        "internal_version": FAKE_IMAGE_DICT["versions"][0]["version"],
        "image_description": FAKE_IMAGE_DICT["name"],
        "uuid_validity": {},
    },
}


class TestManage(TestCase):
    def setUp(self):
        """create all necessary test data, gets called before each test"""

        self.fake_image_dict = copy.deepcopy(FAKE_IMAGE_DICT)
        self.fake_image = Image(**FAKE_IMAGE_DATA)
        self.fake_name = f"{self.fake_image_dict['name']} (1)"
        self.fake_url = "http://url.com"
        self.fake_checksum_url = "https://url.com/image.qcow2.sha512"
        self.fake_checksums_url = "https://url.com/SHA512SUMS"
        self.versions = {
            "1": {
                "url": self.fake_url,
                "meta": {
                    "image_source": self.fake_url,
                    "image_build_date": "2021-01-21",
                },
            },
        }
        self.sorted_versions = ["1"]
        self.previous_image = self.fake_image
        self.imported_image = self.fake_image

        self.file_image_dict = copy.deepcopy(FAKE_IMAGE_DICT)
        self.file_image = Image(**self.file_image_dict)
        self.file_url = "file:///path/to/file.img"
        self.file_image_dict["versions"][0]["url"] = self.file_url
        self.file_versions = {
            "1": {"url": self.file_url, "meta": {"image_source": self.file_url}}
        }

        self.sot = main.ImageManager()
        # since oslo_config.cfg.ConfigOpts objects allow attribute-style access,
        # we can mimick its behaviour with a munch.Munch object
        self.sot.CONF = Munch(
            latest=True,
            check_age=False,
            max_age=90,
            upload=False,
            dry_run=False,
            use_os_hidden=False,
            delete=False,
            keep=False,
            yes_i_really_know_what_i_do=False,
            hide=False,
            deactivate=False,
            cloud="fake-cloud",
            images="etc/images/",
            tag="fake_tag",
            share_image="",
            share_action="add",
            share_domain="default",
            share_target="",
            share_type="project",
            filter="",
            check=False,
            check_only=False,
            hypervisor=None,
            stuck_retry=0,
        )

        # we can also mimick an openstack connection object with a Munch
        self.sot.conn = Munch(current_project_id="123456789", image=Proxy)

    @mock.patch("openstack_image_manager.main.openstack.image.v2._proxy.Proxy.images")
    def test_get_images(self, mock_images):
        """test main.ImageManager.get_images()"""

        mock_images.return_value = [self.fake_image]
        expected_result = {self.fake_image.name: self.fake_image}

        result = self.sot.get_images()
        mock_images.assert_called_once()
        self.assertEqual(result, expected_result)

        mock_images.reset_mock()

        # test with use_os_hidden = True
        self.sot.CONF.use_os_hidden = True
        result = self.sot.get_images()
        mock_images.assert_called_with(**{"os_hidden": True})
        self.assertEqual(mock_images.call_count, 2)
        self.assertEqual(result, expected_result)

    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.get_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.import_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.create_image"
    )
    @mock.patch("builtins.open")
    def test_import_image(self, mock_open, mock_create, mock_import, mock_get_image):
        """test main.ImageManager.import_image()"""

        mock_create.return_value = self.fake_image
        mock_get_image.return_value = self.fake_image
        properties = {
            "container_format": "bare",
            "disk_format": self.fake_image_dict["format"],
            "min_disk": self.fake_image_dict.get("min_disk", 0),
            "min_ram": self.fake_image_dict.get("min_ram", 0),
            "name": self.fake_name,
            "tags": [self.sot.CONF.tag],
            "visibility": "private",
        }

        self.sot.import_image(
            self.fake_image_dict, self.fake_name, self.fake_url, self.versions, "1"
        )

        mock_create.assert_called_once_with(**properties)
        mock_import.assert_called_once_with(
            self.fake_image, method="web-download", uri=self.fake_url
        )
        mock_get_image.assert_called_once_with(self.fake_image)

        mock_create.reset_mock()
        mock_import.reset_mock()
        mock_get_image.reset_mock()

        # test the same function for image with 'file://' url

        # use a dedicated MagicMock for the image object because the
        # implementation will call the upload() function on it
        mock_image_obj = mock.MagicMock()
        mock_image_obj.status = "active"
        mock_create.return_value = mock_image_obj
        mock_get_image.return_value = mock_image_obj
        fake_file_buffer = mock.MagicMock()
        mock_open.return_value = fake_file_buffer

        self.sot.import_image(
            self.file_image_dict, self.fake_name, self.file_url, self.file_versions, "1"
        )

        mock_create.assert_called_once_with(**properties)
        self.assertEqual(mock_image_obj.data, fake_file_buffer)
        mock_import.assert_not_called()
        mock_image_obj.upload.assert_called_with(self.sot.conn.image)
        mock_get_image.assert_called_once_with(mock_image_obj)

    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    @mock.patch("openstack_image_manager.main.ImageManager.read_image_files")
    def test_check_image_age(self, mock_read_image_files, mock_get_images):
        """
        test main.ImageManager.check_image_age()
        """

        mock_read_image_files.return_value = [self.fake_image_dict]
        mock_get_images.return_value = {self.fake_name: self.fake_image}
        too_old_images = self.sot.check_image_age()
        mock_get_images.assert_called_once()
        mock_read_image_files.assert_called_once()
        self.assertEqual(set(), too_old_images)

        mock_read_image_files.reset_mock()
        mock_get_images.reset_mock()
        self.sot.CONF.max_age = 10
        too_old_images = self.sot.check_image_age()
        self.assertIn(self.fake_name, too_old_images)

    @mock.patch("openstack_image_manager.main.ImageManager.set_properties")
    @mock.patch("openstack_image_manager.main.ImageManager.import_image")
    @mock.patch("openstack_image_manager.main.requests.head")
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    @mock.patch("os.path.isfile")
    @mock.patch("os.path.exists")
    def test_process_image(
        self,
        mock_path_exists,
        mock_path_isfile,
        mock_get_images,
        mock_requests,
        mock_import_image,
        mock_set_properties,
    ):
        """test main.ImageManager.process_image()"""

        mock_requests.return_value.status_code = 200
        meta = self.fake_image_dict["meta"]

        result = self.sot.process_image(
            self.fake_image_dict, self.versions, self.sorted_versions, meta
        )

        self.assertEqual(mock_get_images.call_count, 2)
        mock_requests.assert_called_once_with(self.fake_url)
        mock_import_image.assert_called_once_with(
            self.fake_image_dict, self.fake_name, self.fake_url, self.versions, "1"
        )
        mock_set_properties.assert_called_once_with(
            self.fake_image_dict, self.fake_name, self.versions, "1", "", meta
        )
        self.assertEqual(
            result,
            ({self.fake_image_dict["name"]}, mock_get_images.return_value.get(), None),
        )

        mock_get_images.reset_mock()
        mock_requests.reset_mock()
        mock_import_image.reset_mock()
        mock_set_properties.reset_mock()

        # test the same function for image with 'file://' url
        meta = self.file_image_dict["meta"]

        mock_path_exists.return_value = True
        mock_path_isfile.return_value = True

        result = self.sot.process_image(
            self.file_image_dict, self.file_versions, self.sorted_versions, meta
        )

        self.assertEqual(mock_get_images.call_count, 2)
        mock_requests.assert_not_called()
        mock_import_image.assert_called_once_with(
            self.file_image_dict, self.fake_name, self.file_url, self.file_versions, "1"
        )

        mock_get_images.reset_mock()
        mock_requests.reset_mock()
        mock_import_image.reset_mock()
        mock_set_properties.reset_mock()
        mock_path_exists.reset_mock()
        mock_path_isfile.reset_mock()

        # test the same function with dry_run = True
        self.sot.CONF.dry_run = True
        result = self.sot.process_image(
            self.fake_image_dict, self.versions, self.sorted_versions, meta
        )

        mock_get_images.assert_called_once()
        mock_requests.assert_called_once_with(self.fake_url)
        mock_import_image.assert_not_called()
        mock_set_properties.assert_not_called()
        self.assertEqual(result, ({self.fake_image_dict["name"]}, None, None))

    @mock.patch("openstack_image_manager.main.ImageManager.set_properties")
    @mock.patch("openstack_image_manager.main.ImageManager.import_image")
    @mock.patch("openstack_image_manager.main.requests.head")
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_process_image_separator(
        self,
        mock_get_images,
        mock_requests,
        mock_import_image,
        mock_set_properties,
    ):
        mock_requests.return_value.status_code = 200
        meta = self.fake_image_dict["meta"]
        self.fake_image_dict["separator"] = "-"
        self.fake_image_dict["multi"] = False

        result = self.sot.process_image(
            self.fake_image_dict, self.versions, self.sorted_versions, meta
        )

        self.assertIn("Ubuntu 20.04-1", result[0])

    @mock.patch("openstack_image_manager.main.ImageManager.set_properties")
    @mock.patch("openstack_image_manager.main.ImageManager.import_image")
    @mock.patch("openstack_image_manager.main.requests.head")
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_process_image_separator_multi(
        self,
        mock_get_images,
        mock_requests,
        mock_import_image,
        mock_set_properties,
    ):
        mock_old_image = mock.MagicMock()
        mock_old_image.status = "active"
        mock_get_images.return_value = {"Ubuntu 20.04": mock_old_image}

        mock_requests.return_value.status_code = 200
        meta = self.fake_image_dict["meta"]
        self.fake_image_dict["separator"] = "-"
        self.fake_image_dict["multi"] = True

        self.fake_image_dict["versions"].append(
            {
                "build_date": date.fromisoformat("2022-02-22"),
                "version": "2",
                "url": "http://url.com2",
                "checksum": "5678",
            }
        )

        self.versions["2"] = {
            "url": self.fake_url + "2",
            "meta": {
                "image_source": self.fake_url + "2",
                "image_build_date": "2022-02-22",
            },
        }
        self.sorted_versions = ["1", "2"]

        result = self.sot.process_image(
            self.fake_image_dict, self.versions, self.sorted_versions, meta
        )

        self.assertIn("Ubuntu 20.04", result[0])
        self.assertEqual(result[2], mock_old_image)

    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.deactivate_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.remove_tag"
    )
    @mock.patch("openstack_image_manager.main.openstack.image.v2._proxy.Proxy.add_tag")
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.update_image"
    )
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_set_properties(
        self,
        mock_get_images,
        mock_update_image,
        mock_add_tag,
        mock_remove_tag,
        mock_deactivate,
    ):
        """test main.ImageManager.set_properties()"""

        meta = self.fake_image_dict["meta"]
        mock_get_images.return_value = {self.fake_name: self.fake_image}

        self.fake_image_dict["tags"] = ["my_tag"]
        self.fake_image_dict["status"] = "deactivated"

        self.sot.set_properties(
            self.fake_image_dict, self.fake_name, self.versions, "1", "", meta
        )

        mock_get_images.assert_called_once()
        mock_update_image.assert_called()
        mock_add_tag.assert_called_once_with(self.fake_image.id, "my_tag")
        mock_remove_tag.assert_called_once_with(self.fake_image.id, "fake_tag")
        mock_deactivate.assert_called_once_with(self.fake_image.id)

    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.update_image"
    )
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_rename_images(self, mock_get_images, mock_update_image):
        """test main.ImageManager.rename_images()"""

        # test with len(sorted_versions) > 1
        mock_get_images.return_value = {
            self.fake_name: self.fake_image,
            self.fake_image.name: self.fake_image,
        }
        self.sot.rename_images(
            self.fake_image_dict,
            self.sorted_versions,
            self.imported_image,
            self.previous_image,
        )

        mock_get_images.assert_called_once()
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)

        self.assertEqual(mock_update_image.call_count, 2)
        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1 and name in cloud_images
        mock_get_images.return_value = {self.fake_image.name: self.fake_image}
        self.sorted_versions = ["1"]

        self.sot.rename_images(
            self.fake_image_dict,
            self.sorted_versions,
            self.imported_image,
            self.previous_image,
        )
        mock_get_images.assert_called_once()
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)
        self.assertEqual(mock_update_image.call_count, 2)

        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1
        mock_get_images.return_value = {self.fake_name: self.fake_image}

        self.sot.rename_images(
            self.fake_image_dict,
            self.sorted_versions,
            self.imported_image,
            self.previous_image,
        )
        mock_get_images.assert_called_once()
        mock_update_image.assert_called_once_with(self.fake_image.id, name=mock.ANY)

    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.update_image"
    )
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_rename_images_separator(self, mock_get_images, mock_update_image):
        """test main.ImageManager.rename_images()"""

        self.fake_image_dict["separator"] = "-"

        # test with len(sorted_versions) > 1
        mock_get_images.return_value = {
            f"{self.fake_image_dict['name']}-(1)": self.fake_image,
            self.fake_image.name: self.fake_image,
        }
        self.sot.rename_images(
            self.fake_image_dict,
            self.sorted_versions,
            self.imported_image,
            self.previous_image,
        )

        mock_get_images.assert_called_once()
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)

        self.assertEqual(mock_update_image.call_count, 2)
        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1 and name in cloud_images
        mock_get_images.return_value = {self.fake_image.name: self.fake_image}
        self.sorted_versions = ["1"]

        self.sot.rename_images(
            self.fake_image_dict,
            self.sorted_versions,
            self.imported_image,
            self.previous_image,
        )
        mock_get_images.assert_called_once()
        mock_update_image.assert_called_with(self.fake_image.id, name=mock.ANY)
        self.assertEqual(mock_update_image.call_count, 2)

        mock_get_images.reset_mock()
        mock_update_image.reset_mock()

        # test with len(sorted_versions) == 1
        mock_get_images.return_value = {
            f"{self.fake_image_dict['name']}-(1)": self.fake_image
        }

        self.sot.rename_images(
            self.fake_image_dict,
            self.sorted_versions,
            self.imported_image,
            self.previous_image,
        )
        mock_get_images.assert_called_once()
        mock_update_image.assert_called_once_with(self.fake_image.id, name=mock.ANY)

    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.delete_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.update_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.deactivate_image"
    )
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_manage_outdated_images(
        self, mock_get_images, mock_deactivate, mock_update_image, mock_delete_image
    ):
        """test main.ImageManager.manage_outdated_images"""

        managed_images = {"some_image_name"}
        mock_get_images.return_value = {self.fake_image.name: self.fake_image}

        self.sot.manage_outdated_images(managed_images)
        mock_get_images.assert_called_once()
        mock_deactivate.assert_not_called()
        mock_update_image.assert_not_called()
        mock_delete_image.assert_not_called()

    @mock.patch("openstack_image_manager.main.ImageManager.read_image_files")
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.delete_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.update_image"
    )
    @mock.patch(
        "openstack_image_manager.main.openstack.image.v2._proxy.Proxy.deactivate_image"
    )
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_manage_outdated_images_2(
        self,
        mock_get_images,
        mock_deactivate,
        mock_update_image,
        mock_delete_image,
        mock_read_image_files,
    ):
        """test main.ImageManager.manage_outdated_images in delete conditions"""

        managed_images = {"some_image_name"}
        mock_get_images.return_value = {self.fake_image.name + "_2": self.fake_image}
        mock_read_image_files.return_value = [self.fake_image_dict]

        self.sot.CONF.delete = True
        self.sot.CONF.yes_i_really_know_what_i_do = True

        self.sot.manage_outdated_images(managed_images)
        mock_get_images.assert_called_once()
        mock_deactivate.assert_called_once()
        mock_update_image.assert_called_once()
        mock_delete_image.assert_called_once()

        fake_image_dict_2 = dict(self.fake_image_dict)
        fake_image_dict_2["keep"] = True
        mock_read_image_files.return_value = [fake_image_dict_2]

        mock_get_images.reset_mock()
        mock_deactivate.reset_mock()
        mock_update_image.reset_mock()
        mock_delete_image.reset_mock()
        self.sot.manage_outdated_images(managed_images)
        mock_get_images.assert_called_once()
        mock_deactivate.assert_called_once()
        mock_update_image.assert_called_once()
        mock_delete_image.assert_not_called()

    @mock.patch("openstack_image_manager.main.ImageManager.unshare_image_with_project")
    @mock.patch("openstack_image_manager.main.ImageManager.share_image_with_project")
    @mock.patch("openstack_image_manager.main.ImageManager.validate_yaml_schema")
    @mock.patch("openstack_image_manager.main.ImageManager.manage_outdated_images")
    @mock.patch("openstack_image_manager.main.ImageManager.process_images")
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    @mock.patch("openstack_image_manager.main.ImageManager.read_image_files")
    @mock.patch("openstack_image_manager.main.openstack.connect")
    def test_main(
        self,
        mock_connect,
        mock_read_image_files,
        mock_get_images,
        mock_process_images,
        mock_manage_outdated,
        mock_validate_yaml,
        mock_share_image,
        mock_unshare_image,
    ):
        """test main.ImageManager.main()"""
        self.sot.CONF.upload = True
        mock_read_image_files.return_value = [self.fake_image_dict]
        mock_process_images.return_value = set()

        self.sot.main()

        mock_connect.assert_called_once_with(cloud=self.sot.CONF.cloud)
        mock_read_image_files.assert_called_once()
        mock_process_images.assert_called_once_with([self.fake_image_dict])
        mock_manage_outdated.assert_called_once_with(set())
        mock_validate_yaml.assert_not_called()
        mock_share_image.assert_not_called()
        mock_unshare_image.assert_not_called()

        # reset
        mock_connect.reset_mock()
        mock_read_image_files.reset_mock()
        mock_get_images.reset_mock()
        mock_process_images.reset_mock()
        mock_manage_outdated.reset_mock()
        mock_validate_yaml.reset_mock()
        mock_share_image.reset_mock()
        mock_unshare_image.reset_mock()

        # test with check = True
        self.sot.CONF.check = True
        self.sot.CONF.dry_run = False

        self.sot.main()
        mock_connect.assert_called_once_with(cloud=self.sot.CONF.cloud)
        mock_read_image_files.assert_called_once()
        mock_process_images.assert_called_once_with([self.fake_image_dict])
        mock_manage_outdated.assert_called_once_with(set())
        mock_validate_yaml.assert_called_once()
        mock_share_image.assert_not_called()
        mock_unshare_image.assert_not_called()

        # reset
        mock_connect.reset_mock()
        mock_read_image_files.reset_mock()
        mock_get_images.reset_mock()
        mock_process_images.reset_mock()
        mock_manage_outdated.reset_mock()
        mock_validate_yaml.reset_mock()
        mock_share_image.reset_mock()
        mock_unshare_image.reset_mock()

        # test with check_only = True
        self.sot.CONF.check = False
        self.sot.CONF.check_only = True
        self.sot.CONF.dry_run = False

        self.sot.main()
        mock_connect.assert_not_called()
        mock_read_image_files.assert_not_called()
        mock_process_images.assert_not_called()
        mock_manage_outdated.assert_not_called()
        mock_validate_yaml.assert_called_once()
        mock_share_image.assert_not_called()
        mock_unshare_image.assert_not_called()

        # reset
        mock_connect.reset_mock()
        mock_read_image_files.reset_mock()
        mock_get_images.reset_mock()
        mock_process_images.reset_mock()
        mock_manage_outdated.reset_mock()
        mock_validate_yaml.reset_mock()
        mock_share_image.reset_mock()
        mock_unshare_image.reset_mock()

        # test with check_only = True and check = True
        self.sot.CONF.check = True
        self.sot.CONF.check_only = True
        self.sot.CONF.dry_run = False

        self.sot.main()
        mock_connect.assert_not_called()
        mock_read_image_files.assert_not_called()
        mock_process_images.assert_not_called()
        mock_manage_outdated.assert_not_called()
        mock_validate_yaml.assert_called_once()
        mock_share_image.assert_not_called()
        mock_unshare_image.assert_not_called()

    def test_validate_images(self):
        """Validate the image definitions in this repo against the schema"""
        self.sot.CONF.check_only = True

        # When image validation fails, we sys.exit and fail the test
        self.sot.main()

    @mock.patch("openstack_image_manager.main.os.path.isfile")
    @mock.patch("openstack_image_manager.main.os.listdir")
    @mock.patch("builtins.open", mock.mock_open(read_data=str(FAKE_YML)))
    def test_read_image_files(self, mock_listdir, mock_isfile):
        """test main.ImageManager.read_image_files()"""
        mock_listdir.return_value = ["fake.yml"]
        mock_isfile.return_value = True

        result = self.sot.read_image_files()
        self.assertEqual(result, [self.fake_image_dict])

    @mock.patch("openstack_image_manager.main.ImageManager.rename_images")
    @mock.patch("openstack_image_manager.main.ImageManager.process_image")
    def test_process_images(self, mock_process_image, mock_rename_images):
        """test main.ImageManager.process_images()"""
        meta = self.fake_image_dict["meta"]
        self.fake_image_dict["tags"] = [
            self.sot.CONF.tag,
            f"os:{self.fake_image_dict['meta']['os_distro']}",
        ]
        mock_process_image.return_value = (
            {self.fake_image_dict["name"]},
            self.imported_image,
            self.previous_image,
        )

        result = self.sot.process_images([self.fake_image_dict])

        mock_process_image.assert_called_once_with(
            self.fake_image_dict, self.versions, ["1"], meta
        )
        mock_rename_images.assert_called_once_with(
            self.fake_image_dict,
            ["1"],
            self.imported_image,
            self.previous_image,
        )

        self.assertEqual(result, {self.fake_image_dict["name"]})
        self.assertEqual(
            self.fake_image_dict["meta"]["image_name"], self.fake_image_dict["name"]
        )

    def test_is_checksum(self):
        """test main.ImageManager.is_checksum()"""
        for checksum in (MD5, SHA1, SHA256, SHA512):
            self.assertTrue(self.sot.is_checksum(checksum))
            self.assertTrue(self.sot.is_checksum(checksum.upper()))

        # correct length, but not hexadecimal
        self.assertFalse(self.sot.is_checksum("x" * 64))
        # hexadecimal, but not a digest length
        self.assertFalse(self.sot.is_checksum("abc123"))
        self.assertFalse(self.sot.is_checksum(SHA256[:-1]))
        # sha256sum sidecar line instead of a bare digest
        self.assertFalse(self.sot.is_checksum(f"{SHA256}  image.qcow2"))
        self.assertFalse(self.sot.is_checksum(""))

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksum_url(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksum_url()"""
        mock_get.return_value = mock.Mock(text=f"{SHA512}\n")

        result = self.sot.get_checksum_from_checksum_url(self.fake_checksum_url)

        self.assertEqual(result, SHA512)
        mock_get.assert_called_once_with(self.fake_checksum_url, timeout=mock.ANY)

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksum_url_invalid_content(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksum_url() with junk"""
        mock_get.return_value = mock.Mock(text="<html>not a checksum</html>")

        result = self.sot.get_checksum_from_checksum_url(self.fake_checksum_url)

        self.assertEqual(result, "")

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksum_url_http_error(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksum_url() with an
        HTTP error status whose body looks like a valid checksum"""
        mock_get.return_value = mock.Mock(
            text=SHA512,
            raise_for_status=mock.Mock(
                side_effect=requests.exceptions.HTTPError("404")
            ),
        )

        result = self.sot.get_checksum_from_checksum_url(self.fake_checksum_url)

        self.assertEqual(result, "")

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksum_url_request_exception(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksum_url() with a
        connection failure"""
        mock_get.side_effect = requests.exceptions.ConnectionError("unreachable")

        result = self.sot.get_checksum_from_checksum_url(self.fake_checksum_url)

        self.assertEqual(result, "")

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksums_url(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksums_url()"""
        checksums_file = f"{SHA256} *other.qcow2\n{SHA512} *image.qcow2\n"
        mock_get.return_value = mock.Mock(text=checksums_file)

        result = self.sot.get_checksum_from_checksums_url(
            "https://url.com/image.qcow2", self.fake_checksums_url
        )

        self.assertEqual(result, SHA512)
        mock_get.assert_called_once_with(self.fake_checksums_url, timeout=mock.ANY)

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksums_url_http_error(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksums_url() with an
        HTTP error status whose body looks like a valid checksums file"""
        mock_get.return_value = mock.Mock(
            text=f"{SHA512} *image.qcow2\n",
            raise_for_status=mock.Mock(
                side_effect=requests.exceptions.HTTPError("404")
            ),
        )

        result = self.sot.get_checksum_from_checksums_url(
            "https://url.com/image.qcow2", self.fake_checksums_url
        )

        self.assertEqual(result, "")

    @mock.patch("openstack_image_manager.main.requests.get")
    def test_get_checksum_from_checksums_url_request_exception(self, mock_get):
        """test main.ImageManager.get_checksum_from_checksums_url() with a
        connection failure"""
        mock_get.side_effect = requests.exceptions.ConnectionError("unreachable")

        result = self.sot.get_checksum_from_checksums_url(
            "https://url.com/image.qcow2", self.fake_checksums_url
        )

        self.assertEqual(result, "")

    @mock.patch("openstack_image_manager.main.ImageManager.import_image")
    @mock.patch(
        "openstack_image_manager.main.ImageManager.get_checksum_from_checksum_url"
    )
    @mock.patch("openstack_image_manager.main.ImageManager.get_images")
    def test_process_image_checksum_lookup_failure(
        self, mock_get_images, mock_get_checksum, mock_import_image
    ):
        """test main.ImageManager.process_image() when the upstream checksum
        of a latest image cannot be determined"""
        mock_get_images.return_value = {}
        mock_get_checksum.return_value = ""
        versions = {
            "latest": {
                "url": "https://url.com/image.qcow2",
                "checksum_url": self.fake_checksum_url,
                "meta": {},
            }
        }
        meta = self.fake_image_dict["meta"]

        result = self.sot.process_image(
            self.fake_image_dict, versions, ["latest"], meta
        )

        self.assertEqual(result, (set(), None, None))
        self.assertTrue(self.sot.exit_with_error)
        mock_import_image.assert_not_called()

    @mock.patch("openstack_image_manager.main.ImageManager.manage_outdated_images")
    @mock.patch("openstack_image_manager.main.ImageManager.process_images")
    @mock.patch("openstack_image_manager.main.ImageManager.read_image_files")
    @mock.patch("openstack_image_manager.main.openstack.connect")
    def test_main_skips_cleanup_on_error(
        self,
        mock_connect,
        mock_read_image_files,
        mock_process_images,
        mock_manage_outdated,
    ):
        """test that main.ImageManager.main() does not clean up outdated
        images when errors occurred during image processing"""
        self.sot.CONF.upload = True
        mock_read_image_files.return_value = [self.fake_image_dict]

        def fail_processing(images):
            self.sot.exit_with_error = True
            return set()

        mock_process_images.side_effect = fail_processing

        with self.assertRaises(SystemExit):
            self.sot.main()

        mock_process_images.assert_called_once_with([self.fake_image_dict])
        mock_manage_outdated.assert_not_called()

    def test_schema_url_fields_reject_ftp(self):
        """the checksum URL fields must only accept URLs that
        requests.get() can actually fetch (no FTP adapter)"""
        schema = yamale.make_schema("etc/schema.yaml")

        for field in ("checksum_url", "checksums_url", "latest_checksum_url"):
            for scheme, valid in (
                ("https", True),
                ("http", True),
                ("ftp", False),
                ("ftps", False),
            ):
                with self.subTest(field=field, scheme=scheme):
                    image = copy.deepcopy(SCHEMA_TEST_IMAGE_DICT)
                    url = f"{scheme}://url.com/image.qcow2.sha512"
                    if field == "latest_checksum_url":
                        image[field] = url
                    else:
                        image["versions"][0][field] = url
                    content = yaml.safe_dump({"images": [image]})
                    data = yamale.make_data(content=content)
                    if valid:
                        yamale.validate(schema, data)
                    else:
                        with self.assertRaises(YamaleError):
                            yamale.validate(schema, data)

    @mock.patch("openstack_image_manager.main.ImageManager.read_image_files")
    def test_collect_planned_uploads(self, mock_read_image_files):
        multi_image = {
            "name": "Ubuntu 20.04",
            "multi": True,
            "versions": [
                {"version": "1", "url": "https://url.com/v1.qcow2"},
                {"version": "2", "url": "https://url.com/v2.qcow2"},
            ],
        }
        single_image = {
            "name": "Cirros",
            "multi": False,
            "versions": [{"version": "0.6.2", "url": "https://url.com/cirros.img"}],
        }
        mock_read_image_files.return_value = [multi_image, single_image]

        # without --latest all versions of a multi image are planned
        self.sot.CONF.latest = False
        planned = self.sot.collect_planned_uploads()
        self.assertEqual(
            planned,
            [
                ("Ubuntu 20.04 (1)", "https://url.com/v1.qcow2"),
                ("Ubuntu 20.04 (2)", "https://url.com/v2.qcow2"),
                ("Cirros 0.6.2", "https://url.com/cirros.img"),
            ],
        )

        # with --latest only the latest version of a multi image is planned
        self.sot.CONF.latest = True
        planned = self.sot.collect_planned_uploads()
        self.assertEqual(
            planned,
            [
                ("Ubuntu 20.04 (2)", "https://url.com/v2.qcow2"),
                ("Cirros 0.6.2", "https://url.com/cirros.img"),
            ],
        )

    @mock.patch("openstack_image_manager.main.ImageManager.read_image_files")
    def test_collect_planned_uploads_prefers_mirror_url(self, mock_read_image_files):
        mock_read_image_files.return_value = [
            {
                "name": "Cirros",
                "multi": False,
                "versions": [
                    {
                        "version": "1",
                        "url": "https://url.com/original.img",
                        "mirror_url": "https://mirror.com/mirror.img",
                    }
                ],
            }
        ]
        planned = self.sot.collect_planned_uploads()
        self.assertEqual(planned, [("Cirros 1", "https://mirror.com/mirror.img")])

    @mock.patch("openstack_image_manager.main.requests.head")
    def test_get_remote_size(self, mock_head):
        mock_head.return_value.headers = {"Content-Length": "2048"}
        self.assertEqual(self.sot.get_remote_size("https://url.com/image.img"), 2048)

        # missing Content-Length header -> None
        mock_head.return_value.headers = {}
        self.assertIsNone(self.sot.get_remote_size("https://url.com/image.img"))

        # request failure -> None
        mock_head.side_effect = requests.RequestException()
        self.assertIsNone(self.sot.get_remote_size("https://url.com/image.img"))

        # no url at all -> None
        self.assertIsNone(self.sot.get_remote_size(None))

    def test_format_size(self):
        self.assertEqual(self.sot.format_size(512), "512.0 B")
        self.assertEqual(self.sot.format_size(1024), "1.0 KiB")
        self.assertEqual(self.sot.format_size(5 * 1024**3), "5.0 GiB")

    def test_build_upload_command(self):
        self.sot.CONF.cloud = "openstack"
        self.sot.CONF.images = "etc/images/"
        self.sot.CONF.filter = ""
        self.sot.CONF.latest = False
        self.assertEqual(
            self.sot.build_upload_command(), "openstack-image-manager --upload"
        )

        self.sot.CONF.cloud = "mycloud"
        self.sot.CONF.filter = "Ubuntu 20.04"
        self.sot.CONF.latest = True
        self.assertEqual(
            self.sot.build_upload_command(),
            "openstack-image-manager --upload --cloud mycloud "
            "--filter 'Ubuntu 20.04' --latest",
        )

    @mock.patch("openstack_image_manager.main.ImageManager.create_connection")
    @mock.patch("openstack_image_manager.main.ImageManager.get_remote_size")
    @mock.patch("openstack_image_manager.main.ImageManager.collect_planned_uploads")
    @mock.patch("openstack_image_manager.main.typer.echo")
    def test_show_upload_preview(
        self, mock_echo, mock_collect, mock_size, mock_connection
    ):
        mock_collect.return_value = [("Cirros 0.6.2", "https://url.com/cirros.img")]
        mock_size.return_value = 5 * 1024**3

        self.sot.CONF.cloud = "openstack"
        self.sot.CONF.images = "etc/images/"
        self.sot.CONF.filter = ""
        self.sot.CONF.latest = False

        self.sot.show_upload_preview()

        # the preview must never connect to OpenStack
        mock_connection.assert_not_called()

        output = "\n".join(str(call.args[0]) for call in mock_echo.call_args_list)
        self.assertIn("Cirros 0.6.2", output)
        self.assertIn("Total download size", output)
        self.assertIn("Estimated upload time", output)
        self.assertIn("openstack-image-manager --upload", output)
        self.assertIn(main.DOCS_URL, output)

    @mock.patch("openstack_image_manager.main.ImageManager.create_connection")
    @mock.patch("openstack_image_manager.main.ImageManager.collect_planned_uploads")
    @mock.patch("openstack_image_manager.main.typer.echo")
    def test_show_upload_preview_no_images(
        self, mock_echo, mock_collect, mock_connection
    ):
        mock_collect.return_value = []
        self.sot.show_upload_preview()
        mock_connection.assert_not_called()
        output = "\n".join(str(call.args[0]) for call in mock_echo.call_args_list)
        self.assertIn("No enabled images found", output)
        self.assertIn(main.DOCS_URL, output)
