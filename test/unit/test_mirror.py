# SPDX-License-Identifier: Apache-2.0

import hashlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

import requests
from minio.error import S3Error
from patoolib.util import PatoolError
from urllib3 import HTTPHeaderDict
from urllib3.exceptions import ProtocolError

import contrib.mirror as mirror

PAYLOAD = b"image-bytes"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()

# Fixtures follow the shape of real etc/images entries, one per naming branch
# mirror_paths has to handle.
# Their checksums are the digest of the payload the fake download serves.

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
            "checksum": f"sha256:{PAYLOAD_SHA256}",
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
            "checksum": f"sha256:{PAYLOAD_SHA256}",
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
            "checksum": f"sha256:{PAYLOAD_SHA256}",
        }
    ],
}

BUCKET = "osism"


def _missing_object():
    return S3Error(None, "NoSuchKey", "not found", "object", "request", "host")


class _FakeClient:
    """Minimal stand-in for minio.Minio that records what the mirror step does.

    Metadata is stored the way minio stores it: user keys are prefixed with
    X-Amz-Meta- on the way in and read back out of a case-insensitive header
    mapping, so production code has to look them up as minio presents them.
    """

    def __init__(self, existing=()):
        self.existing = {name: HTTPHeaderDict() for name in existing}
        self.statted = []
        self.uploaded = []

    def bucket_exists(self, bucket):
        return True

    def stat_object(self, bucket, name):
        self.statted.append(name)
        if name not in self.existing:
            raise _missing_object()
        return mock.Mock(metadata=self.existing[name])

    def fput_object(self, bucket, name, path, **kwargs):
        self.uploaded.append((name, path, kwargs))
        headers = HTTPHeaderDict()
        for key, value in (kwargs.get("metadata") or {}).items():
            headers[f"X-Amz-Meta-{key}"] = value
        self.existing[name] = headers


class _BrokenStream:
    """Stands in for a urllib3 response whose transfer dies partway through.

    Real urllib3 responses expose stream(); requests uses it when present and
    translates urllib3 errors raised from it, so the fake has to have it too.
    """

    def stream(self, chunk_size, decode_content=True):
        yield b"partial-"
        raise ProtocolError("connection broken: incomplete read")

    def read(self, size=-1):
        raise ProtocolError("connection broken: incomplete read")


def _response(payload=PAYLOAD, status=200):
    """A real requests.Response, so raise_for_status() behaves as in production."""
    response = requests.Response()
    response.status_code = status
    response.raw = io.BytesIO(payload)
    return response


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

    def test_download_uses_a_request_timeout(self):
        # A mirror that accepts the connection and then stalls must not hang
        # the run forever; requests only enforces that if asked to.
        client = _FakeClient()

        with mock.patch.object(mirror.requests, "get", return_value=_response()) as get:
            mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        self.assertEqual(get.call_args.kwargs["timeout"], mirror.REQUESTS_TIMEOUT)


class DownloadFailureTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def test_error_response_is_never_uploaded(self):
        client = _FakeClient()

        with mock.patch.object(
            mirror.requests, "get", return_value=_response(b"<html>502</html>", 502)
        ):
            ok = mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])

    def test_error_response_leaves_no_local_file_behind(self):
        # upload=False, so nothing else can clean up after the failed download.
        client = _FakeClient()

        with mock.patch.object(
            mirror.requests, "get", return_value=_response(b"<html>404</html>", 404)
        ):
            mirror.mirror_version(
                client, BUCKET, UBUNTU, UBUNTU["versions"][0], upload=False
            )

        self.assertEqual(os.listdir("."), [])

    def test_connection_failure_is_reported_not_raised(self):
        client = _FakeClient()

        with mock.patch.object(
            mirror.requests, "get", side_effect=requests.ConnectionError("no route")
        ):
            ok = mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])

    def test_failure_midway_through_the_stream_is_reported_not_raised(self):
        # Reading response.raw goes straight to urllib3, so a mid-stream
        # failure is a urllib3 error, not a requests one.
        client = _FakeClient()
        broken = _response()
        broken.raw = _BrokenStream()

        with mock.patch.object(mirror.requests, "get", return_value=broken):
            ok = mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])

    def test_failed_stream_leaves_no_partial_file(self):
        client = _FakeClient()
        broken = _response()
        broken.raw = _BrokenStream()

        with mock.patch.object(mirror.requests, "get", return_value=broken):
            mirror.mirror_version(
                client, BUCKET, UBUNTU, UBUNTU["versions"][0], upload=False
            )

        self.assertEqual(os.listdir("."), [])

    def test_successful_mirror_reports_success(self):
        client = _FakeClient()

        with mock.patch.object(mirror.requests, "get", return_value=_response()):
            ok = mirror.mirror_version(client, BUCKET, UBUNTU, UBUNTU["versions"][0])

        self.assertIs(ok, True)


def _version_with_checksum(image, checksum):
    version = dict(image["versions"][0])
    version["checksum"] = checksum
    return version


class ChecksumTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        self.payload = PAYLOAD

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def _mirror(self, version):
        client = _FakeClient()
        with mock.patch.object(
            mirror.requests, "get", return_value=_response(self.payload)
        ):
            ok = mirror.mirror_version(client, BUCKET, UBUNTU, version)
        return ok, client

    def test_mismatching_checksum_is_not_uploaded(self):
        version = _version_with_checksum(UBUNTU, "sha256:" + "0" * 64)

        ok, client = self._mirror(version)

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])

    def test_matching_checksum_is_uploaded(self):
        digest = hashlib.sha256(self.payload).hexdigest()
        version = _version_with_checksum(UBUNTU, f"sha256:{digest}")

        ok, client = self._mirror(version)

        self.assertIs(ok, True)
        self.assertEqual(len(client.uploaded), 1)

    def test_algorithm_comes_from_the_definition(self):
        # Two catalog entries use sha512, so the algorithm cannot be hardcoded.
        digest = hashlib.sha512(self.payload).hexdigest()
        version = _version_with_checksum(UBUNTU, f"sha512:{digest}")

        ok, _ = self._mirror(version)

        self.assertIs(ok, True)

    def test_mismatch_leaves_no_local_file_behind(self):
        # upload=False, so nothing else can clean up after the rejected file.
        version = _version_with_checksum(UBUNTU, "sha256:" + "0" * 64)
        client = _FakeClient()

        with mock.patch.object(
            mirror.requests, "get", return_value=_response(self.payload)
        ):
            mirror.mirror_version(client, BUCKET, UBUNTU, version, upload=False)

        self.assertEqual(os.listdir("."), [])

    def _extracting(self, produced):
        """Stand in for patoolib, producing the bytes the archive unpacks to."""

        def extract(name, outdir):
            os.makedirs(outdir, exist_ok=True)
            target = mirror.mirror_paths(TALOS, TALOS["versions"][0]).filename
            with open(os.path.join(outdir, target), "wb") as fp:
                fp.write(produced)

        return extract

    def test_compressed_source_is_checked_after_decompression(self):
        # For a compressed source the mirror stores the unpacked image, and the
        # definition's checksum describes that -- contrib/update-gardenlinux.py
        # hashes the extracted qcow2, and main.py downloads mirror_url. So the
        # archive's own bytes are not what has to match.
        unpacked = b"unpacked-image-bytes"
        version = _version_with_checksum(
            TALOS, f"sha256:{hashlib.sha256(unpacked).hexdigest()}"
        )
        client = _FakeClient()

        with mock.patch.object(
            mirror.requests, "get", return_value=_response(b"archive-bytes")
        ):
            with mock.patch.object(
                mirror.patoolib, "extract_archive", self._extracting(unpacked)
            ):
                ok = mirror.mirror_version(client, BUCKET, TALOS, version)

        self.assertIs(ok, True)
        self.assertEqual(len(client.uploaded), 1)

    def test_unpacked_image_that_does_not_match_is_not_uploaded(self):
        version = _version_with_checksum(TALOS, "sha256:" + "0" * 64)
        client = _FakeClient()

        with mock.patch.object(
            mirror.requests, "get", return_value=_response(b"archive-bytes")
        ):
            with mock.patch.object(
                mirror.patoolib, "extract_archive", self._extracting(b"wrong-image")
            ):
                ok = mirror.mirror_version(client, BUCKET, TALOS, version)

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])


class ObjectMetadataTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def _mirror(self, client, version):
        with mock.patch.object(mirror.requests, "get", return_value=_response()):
            return mirror.mirror_version(client, BUCKET, UBUNTU, version)

    def test_version_without_a_checksum_records_no_provenance(self):
        # The schema allows a version with no checksum; there is then nothing
        # meaningful to record, and an empty value would read back as garbage.
        client = _FakeClient()
        version = dict(UBUNTU["versions"][0])
        del version["checksum"]

        ok = self._mirror(client, version)

        self.assertIs(ok, True)
        self.assertNotIn("metadata", client.uploaded[0][2])

    def test_unverified_download_records_no_provenance(self):
        # With --no-checksum the bytes were never checked, so stamping them as
        # matching the definition would make a later run trust them.
        client = _FakeClient()

        with mock.patch.object(mirror.requests, "get", return_value=_response()):
            ok = mirror.mirror_version(
                client, BUCKET, UBUNTU, UBUNTU["versions"][0], checksum=False
            )

        self.assertIs(ok, True)
        self.assertNotIn("metadata", client.uploaded[0][2])

    def test_upload_records_which_checksum_it_was_mirrored_for(self):
        client = _FakeClient()
        version = UBUNTU["versions"][0]

        self._mirror(client, version)

        stored = client.stat_object(BUCKET, client.uploaded[0][0])
        self.assertEqual(
            stored.metadata.get("x-amz-meta-upstream-checksum"), version["checksum"]
        )

    def test_object_matching_the_definition_is_left_alone(self):
        client = _FakeClient()
        version = UBUNTU["versions"][0]
        self._mirror(client, version)

        ok = self._mirror(client, version)

        self.assertIs(ok, True)
        self.assertEqual(len(client.uploaded), 1)

    def test_object_mirrored_for_another_checksum_fails(self):
        client = _FakeClient()
        self._mirror(client, UBUNTU["versions"][0])

        changed = _version_with_checksum(UBUNTU, "sha256:" + "0" * 64)
        ok = self._mirror(client, changed)

        self.assertIs(ok, False)

    def test_mismatching_object_is_not_overwritten(self):
        client = _FakeClient()
        self._mirror(client, UBUNTU["versions"][0])

        changed = _version_with_checksum(UBUNTU, "sha256:" + "0" * 64)
        self._mirror(client, changed)

        self.assertEqual(len(client.uploaded), 1)

    def test_object_without_metadata_is_skipped_without_failing(self):
        # Everything mirrored before this change has no recorded checksum.
        client = _FakeClient(
            existing={"openstack-images/ubuntu-24.04/20260108-ubuntu-24.04.qcow2"}
        )

        ok = self._mirror(client, UBUNTU["versions"][0])

        self.assertIs(ok, True)
        self.assertEqual(client.uploaded, [])


class ExtractionFailureTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def _mirror(self, extract):
        client = _FakeClient()
        with mock.patch.object(
            mirror.requests, "get", return_value=_response(b"archive-bytes")
        ):
            with mock.patch.object(mirror.patoolib, "extract_archive", extract):
                ok = mirror.mirror_version(client, BUCKET, TALOS, TALOS["versions"][0])
        return ok, client

    def test_unreadable_archive_is_reported_not_raised(self):
        def extract(name, outdir):
            raise PatoolError("unknown archive format")

        ok, client = self._mirror(extract)

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])

    def test_archive_without_the_expected_image_is_reported(self):
        # What gardenlinux actually ships: the archive unpacks to a root
        # filesystem tree, so the image the mirror_url names never appears.
        def extract(name, outdir):
            os.makedirs(os.path.join(outdir, "boot"), exist_ok=True)

        ok, client = self._mirror(extract)

        self.assertIs(ok, False)
        self.assertEqual(client.uploaded, [])

    def test_failed_extraction_leaves_no_downloaded_archive(self):
        def extract(name, outdir):
            raise PatoolError("unknown archive format")

        self._mirror(extract)

        leftovers = [f for f in os.listdir(".") if f != "tmp"]
        self.assertEqual(leftovers, [])


SAMPLE_YML = """\
---
images:
  - name: Ubuntu 24.04
    shortname: ubuntu-24.04
    versions:
      - version: '20260108'
        url: https://cloud-images.ubuntu.com/noble/20260108/noble-server-cloudimg-amd64.img
        mirror_url: https://nbg1.your-objectstorage.com/osism/openstack-images/ubuntu-24.04/20260108-ubuntu-24.04.qcow2
        checksum: sha256:0000000000000000000000000000000000000000000000000000000000000000
"""


class ExitStatusTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.images = os.path.join(self.dir, "images")
        os.mkdir(self.images)
        with open(os.path.join(self.images, "ubuntu.yml"), "w") as fp:
            fp.write(SAMPLE_YML)
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def _run(self, response):
        client = _FakeClient()
        with mock.patch.object(mirror, "Minio", return_value=client):
            with mock.patch.object(mirror.requests, "get", return_value=response):
                mirror.main(
                    debug=False,
                    upload=True,
                    checksum=False,
                    download=True,
                    delete=True,
                    images=self.images,
                    minio_access_key="key",
                    minio_secret_key="secret",
                    minio_server="object.test",
                    minio_bucket=BUCKET,
                )
        return client

    def test_failed_version_exits_non_zero(self):
        with self.assertRaises(SystemExit) as caught:
            self._run(_response(b"<html>502</html>", 502))

        self.assertEqual(caught.exception.code, 1)

    def test_run_without_failures_does_not_exit(self):
        client = self._run(_response())

        self.assertEqual(len(client.uploaded), 1)


if __name__ == "__main__":
    unittest.main()
