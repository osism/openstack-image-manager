# SPDX-License-Identifier: Apache-2.0

import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from minio.error import S3Error

import contrib.mirror as mirror

# Fixtures follow the shape of real etc/images entries, one per naming branch
# mirror_paths has to handle.

UBUNTU = {
    "shortname": "ubuntu-24.04",
    "versions": [
        {
            "version": "20260108",
            "url": "https://cloud-images.ubuntu.com/noble/20260108/noble-server-cloudimg-amd64.img",
            "mirror_url": (
                "https://nbg1.your-objectstorage.com/osism/openstack-images/"
                "ubuntu-24.04/20260108-ubuntu-24.04.qcow2"
            ),
            "checksum": "sha256:" + "a" * 64,
        }
    ],
}

TALOS = {
    "shortname": "talos",
    "versions": [
        {
            "version": "1.11.3",
            "url": "https://factory.talos.dev/image/376567988ad37013/v1.11.3/openstack-amd64.raw.xz",
            "mirror_url": (
                "https://nbg1.your-objectstorage.com/osism/openstack-images/"
                "talos/1.11.3/openstack-amd64"
            ),
            "checksum": "sha256:" + "b" * 64,
        }
    ],
}

GARDENLINUX = {
    "shortname": "gardenlinux",
    "versions": [
        {
            "version": "1592.14",
            "url": (
                "https://github.com/gardenlinux/gardenlinux/releases/download/1592.14/"
                "openstack-gardener_prod-amd64-1592.14-730f446c.tar.xz"
            ),
            "mirror_url": (
                "https://nbg1.your-objectstorage.com/osism/openstack-images/"
                "gardenlinux/1592.14/openstack-gardener_prod-amd64-1592.14-730f446c.qcow2"
            ),
            "checksum": "sha256:" + "c" * 64,
        }
    ],
}

BUCKET = "osism"


def _missing_object():
    return S3Error(None, "NoSuchKey", "not found", "object", "request", "host")


class _FakeClient:
    """Minimal stand-in for minio.Minio that records what the mirror step does."""

    def __init__(self, existing=()):
        self.existing = set(existing)
        self.statted = []
        self.uploaded = []

    def stat_object(self, bucket, name):
        self.statted.append(name)
        if name not in self.existing:
            raise _missing_object()
        return mock.Mock(metadata={})

    def fput_object(self, bucket, name, path, **kwargs):
        self.uploaded.append((name, path, kwargs))


def _response(payload=b"image-bytes"):
    return mock.Mock(raw=io.BytesIO(payload))


class MirrorPathsTest(unittest.TestCase):
    def test_plain_image_keeps_a_flat_directory(self):
        paths = mirror.mirror_paths(UBUNTU, UBUNTU["versions"][0])

        self.assertEqual(paths.dirname, "openstack-images/ubuntu-24.04")
        self.assertEqual(paths.filename, "20260108-ubuntu-24.04.qcow2")
        self.assertEqual(paths.source_filename, "noble-server-cloudimg-amd64.img")

    def test_compressed_source_gets_a_versioned_directory(self):
        paths = mirror.mirror_paths(TALOS, TALOS["versions"][0])

        self.assertEqual(paths.dirname, "openstack-images/talos/1.11.3")
        self.assertEqual(paths.filename, "openstack-amd64")
        self.assertEqual(paths.source_filename, "openstack-amd64.raw")

    def test_tar_source_keeps_its_full_filename(self):
        paths = mirror.mirror_paths(GARDENLINUX, GARDENLINUX["versions"][0])

        self.assertEqual(paths.dirname, "openstack-images/gardenlinux/1592.14")
        self.assertEqual(
            paths.filename, "openstack-gardener_prod-amd64-1592.14-730f446c.qcow2"
        )
        self.assertEqual(
            paths.source_filename,
            "openstack-gardener_prod-amd64-1592.14-730f446c.tar.xz",
        )


class MirrorVersionTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def test_object_already_in_the_bucket_is_not_downloaded(self):
        client = _FakeClient(
            existing={"openstack-images/ubuntu-24.04/20260108-ubuntu-24.04.qcow2"}
        )

        with mock.patch.object(mirror.requests, "get") as get:
            mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        get.assert_not_called()
        self.assertEqual(client.uploaded, [])

    def test_missing_object_is_downloaded_and_uploaded(self):
        client = _FakeClient()

        with mock.patch.object(mirror.requests, "get", return_value=_response()) as get:
            mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        get.assert_called_once()
        self.assertEqual(
            [name for name, _, _ in client.uploaded],
            ["openstack-images/ubuntu-24.04/20260108-ubuntu-24.04.qcow2"],
        )


if __name__ == "__main__":
    unittest.main()
