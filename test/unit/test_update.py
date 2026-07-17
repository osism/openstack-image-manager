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


if __name__ == "__main__":
    unittest.main()
