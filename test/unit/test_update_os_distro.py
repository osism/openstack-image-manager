# SPDX-License-Identifier: Apache-2.0

import io
import tarfile
import unittest

import contrib.update_os_distro as uod

SCHEMA = """\
meta:
  image_description: str(required=False)
  os_distro: enum('arch', 'talos', 'ubuntu')
  os_version: str(required=False)
"""


def make_archive(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class TestExtractDistros(unittest.TestCase):
    def test_extract_distros(self):
        archive = make_archive(
            {
                "data/os/almalinux.org/almalinux-9.xml.in": (
                    "<os><short-id>almalinux9</short-id>"
                    "<distro>almalinux</distro></os>"
                ),
                "data/os/manjaro.org/manjaro.xml.in": (
                    "<os>\n  <distro>Manjaro</distro>\n</os>"
                ),
                "data/os/ubuntu.com/ubuntu-24.04.xml.in": (
                    "<os><distro>ubuntu</distro></os>"
                ),
                "data/os/README": "<distro>ignored</distro>",
            }
        )
        self.assertEqual(
            uod.extract_distros(archive), {"almalinux", "manjaro", "ubuntu"}
        )


class TestSchemaDistros(unittest.TestCase):
    def test_read_schema_distros(self):
        self.assertEqual(uod.read_schema_distros(SCHEMA), {"arch", "talos", "ubuntu"})

    def test_read_schema_distros_missing_enum(self):
        with self.assertRaises(ValueError):
            uod.read_schema_distros("meta:\n  os_distro: str()\n")

    def test_write_schema_distros(self):
        known = uod.read_schema_distros(SCHEMA)
        result = uod.write_schema_distros(SCHEMA, known | {"almalinux", "win"})
        self.assertEqual(
            result,
            SCHEMA.replace(
                "enum('arch', 'talos', 'ubuntu')",
                "enum('almalinux', 'arch', 'talos', 'ubuntu', 'win')",
            ),
        )
        self.assertEqual(
            uod.read_schema_distros(result),
            {"almalinux", "arch", "talos", "ubuntu", "win"},
        )


if __name__ == "__main__":
    unittest.main()
