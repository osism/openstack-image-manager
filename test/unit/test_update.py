# SPDX-License-Identifier: Apache-2.0

import os
import shutil
import tempfile
import unittest
from unittest import mock

import contrib.update as update

# A minimal single-image YAML using the same shape update.py expects.
SAMPLE_YML = """\
---
images:
  - name: Example 1.0
    enable: true
    shortname: example-1.0
    format: qcow2
    latest_checksum_url: https://example.test/SHA256SUMS
    latest_url: https://example.test/example.qcow2
    versions:
      - version: '20200101'
        url: https://example.test/example.qcow2
        mirror_url: https://old.example/openstack-images/example-1.0/20200101-example-1.0.qcow2
        checksum: sha256:0000000000000000000000000000000000000000000000000000000000000000
        build_date: 2020-01-01
"""


def _fake_getter_changed(shortname, latest_checksum_url, latest_url):
    # New checksum + a concrete version so update_image does not call urlopen.
    return ("sha256:" + "1" * 64, latest_url, "20260101")


def _fake_getter_same(shortname, latest_checksum_url, latest_url):
    return ("sha256:" + "0" * 64, latest_url, "20200101")


class WriteContractTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "example.yml")
        with open(self.path, "w") as fp:
            fp.write(SAMPLE_YML)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _read(self):
        with open(self.path) as fp:
            return fp.read()

    def _run(self, dry_run):
        with mock.patch.dict(
            update.IMAGES, {"example": _fake_getter_changed}, clear=True
        ):
            update.main(
                name="example", debug=False, dry_run=dry_run, images_dir=self.dir
            )

    def test_normal_mode_writes_changed_yaml(self):
        before = self._read()
        self._run(dry_run=False)
        after = self._read()
        self.assertNotEqual(before, after)
        self.assertIn("1" * 64, after)

    def test_dry_run_leaves_file_unchanged(self):
        before = self._read()
        self._run(dry_run=True)
        after = self._read()
        self.assertEqual(before, after)

    def test_noop_writes_nothing(self):
        before = self._read()
        with mock.patch.dict(update.IMAGES, {"example": _fake_getter_same}, clear=True):
            update.main(name="example", debug=False, dry_run=False, images_dir=self.dir)
        after = self._read()
        self.assertEqual(before, after)


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "update")
DATED_UBUNTU = "20260705"
DATED_DEBIAN = "20260717-2542"


def _fx(*parts):
    with open(os.path.join(FIXTURES, *parts)) as fp:
        return fp.read()


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


# Map every URL the getters fetch to fixture content.
_URL_MAP = {
    "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/CHECKSUM": (
        "almalinux9",
        "CHECKSUM",
    ),
    "https://cloud.centos.org/centos/7/images/sha256sum.txt": (
        "centos7",
        "sha256sum.txt",
    ),
    "https://cloud.centos.org/centos/9-stream/x86_64/images/CHECKSUM": (
        "centos_stream9",
        "CHECKSUM",
    ),
    "https://download.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud.latest.x86_64.qcow2.CHECKSUM": (
        "rocky9",
        "CHECKSUM",
    ),
    "https://cloud-images.ubuntu.com/noble": ("ubuntu2404", "index.html"),
    f"https://cloud-images.ubuntu.com/noble/{DATED_UBUNTU}/SHA256SUMS": (
        "ubuntu2404",
        "SHA256SUMS",
    ),
    "https://cdimage.debian.org/cdimage/cloud/trixie/daily": (
        "debian13",
        "index.html",
    ),
    f"https://cdimage.debian.org/cdimage/cloud/trixie/daily/{DATED_DEBIAN}/SHA512SUMS": (
        "debian13",
        "SHA512SUMS",
    ),
}


def _fake_get(url, *args, **kwargs):
    return _FakeResponse(_fx(*_URL_MAP[url]))


class GoldenTest(unittest.TestCase):
    @mock.patch("contrib.update.requests.get", side_effect=_fake_get)
    def test_almalinux9(self, _):
        checksum, url, version = update.get_latest_default(
            "almalinux-9",
            "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/CHECKSUM",
            "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2",
        )
        self.assertEqual(
            checksum,
            "sha256:c397eed7023e92c841155831b1f47e26300e5bef0f0256c129322307c897a251",
        )
        self.assertTrue(url.endswith("AlmaLinux-9-GenericCloud-latest.x86_64.qcow2"))
        self.assertIsNone(version)

    @mock.patch("contrib.update.requests.get", side_effect=_fake_get)
    def test_centos7(self, _):
        checksum, url, version = update.get_latest_default(
            "centos-7",
            "https://cloud.centos.org/centos/7/images/sha256sum.txt",
            r"https://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud-HEREBE\d+\.qcow2$DRAGONS",
        )
        self.assertEqual(
            checksum,
            "sha256:284aab2b23d91318f169ff464bce4d53404a15a0618ceb34562838c59af4adea",
        )
        self.assertEqual(
            url,
            "https://cloud.centos.org/centos/7/images/CentOS-7-x86_64-GenericCloud-2211.qcow2",
        )
        self.assertIsNone(version)

    @mock.patch("contrib.update.requests.get", side_effect=_fake_get)
    def test_centos_stream9(self, _):
        stream9_url = (
            "https://cloud.centos.org/centos/9-stream/x86_64/images/"
            r"CentOS-Stream-GenericCloud-9-HEREBE\d+\.\dDRAGONS.x86_64.qcow2"
        )
        checksum, url, version = update.get_latest_default(
            "centos-stream-9",
            "https://cloud.centos.org/centos/9-stream/x86_64/images/CHECKSUM",
            stream9_url,
        )
        self.assertEqual(
            checksum,
            "sha256:2aa1716dc75fc5485df1b221d3d930f276024d70024f68f9ee047dad0e03d85d",
        )
        self.assertEqual(
            url,
            "https://cloud.centos.org/centos/9-stream/x86_64/images/"
            "CentOS-Stream-GenericCloud-9-20260714.1.x86_64.qcow2",
        )
        self.assertIsNone(version)

    @mock.patch("contrib.update.requests.get", side_effect=_fake_get)
    def test_rocky9(self, _):
        rocky9_base = "https://download.rockylinux.org/pub/rocky/9/images/x86_64/"
        checksum, url, version = update.get_latest_default(
            "rocky-9",
            rocky9_base + "Rocky-9-GenericCloud.latest.x86_64.qcow2.CHECKSUM",
            rocky9_base + "Rocky-9-GenericCloud.latest.x86_64.qcow2",
        )
        self.assertEqual(
            checksum,
            "sha256:92c206cc6f790c61583247eefe87890f8828420662c17cacf247cec78ab4eec8",
        )
        self.assertEqual(
            url,
            rocky9_base + "Rocky-9-GenericCloud.latest.x86_64.qcow2",
        )
        self.assertIsNone(version)

    @mock.patch("contrib.update.requests.get", side_effect=_fake_get)
    def test_ubuntu(self, _):
        checksum, url, version = update.get_latest_debubu(
            "ubuntu-24.04",
            "https://cloud-images.ubuntu.com/noble/current/SHA256SUMS",
            "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        )
        self.assertEqual(
            checksum,
            "sha256:ffe6203da54deeb6db5d2a98a83f9ec8e55f149d3f7ba622e1abe5fa966ee3d6",
        )
        self.assertEqual(
            url,
            "https://cloud-images.ubuntu.com/noble/20260705/noble-server-cloudimg-amd64.img",
        )
        self.assertEqual(version, "20260705")

    @mock.patch("contrib.update.requests.get", side_effect=_fake_get)
    def test_debian(self, _):
        checksum, url, version = update.get_latest_debubu(
            "debian-13",
            "https://cdimage.debian.org/cdimage/cloud/trixie/daily/latest/SHA512SUMS",
            "https://cdimage.debian.org/cdimage/cloud/trixie/daily/latest/debian-13-genericcloud-amd64-daily.qcow2",
        )
        self.assertEqual(
            checksum,
            "sha512:"
            "fcc52bdff35697583f9331b64c688db6681fea98c024a1db185d8857b167f4e"
            "1838ead7037f18c12e432229354b1253f29e881a040ce0f5636801576e715b4b8",
        )
        self.assertEqual(
            url,
            "https://cdimage.debian.org/cdimage/cloud/trixie/daily/"
            "20260717-2542/debian-13-genericcloud-amd64-daily-20260717-2542.qcow2",
        )
        self.assertEqual(version, "20260717")


if __name__ == "__main__":
    unittest.main()
