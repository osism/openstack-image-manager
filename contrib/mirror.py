# SPDX-License-Identifier: Apache-2.0

import hashlib
import os
import patoolib
import re
import requests
import shutil
import sys
import typer
import yaml

from loguru import logger
from minio import Minio
from minio.error import S3Error
from os import listdir
from os.path import isfile, join
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

# Streaming chunk size for downloads and hashing.
CHUNK_SIZE = 1024 * 1024

# Mirrors that accept a connection and then stall must not hang the run.
# Matches REQUESTS_TIMEOUT in openstack_image_manager/main.py.
REQUESTS_TIMEOUT = 30

# Object metadata recording which definition an object was mirrored for.
# minio prefixes user metadata with X-Amz-Meta- on upload.
UPSTREAM_CHECKSUM_KEY = "upstream-checksum"
UPSTREAM_CHECKSUM_HEADER = "x-amz-meta-upstream-checksum"

app = typer.Typer(add_completion=False)


def file_checksum(path, algorithm):
    """Return the hex digest of a file using the named hash algorithm."""
    digest = hashlib.new(algorithm)
    with open(path, "rb") as fp:
        while chunk := fp.read(8192):
            digest.update(chunk)

    return digest.hexdigest()


class MirrorPaths(NamedTuple):
    """Where one image version lives upstream and in the mirror bucket."""

    dirname: str
    filename: str
    source_filename: str
    source_extension: str


def mirror_paths(image, version):
    """Derive the bucket path and local download name for one version."""
    source_path = urlparse(version["url"])
    mirror_path = urlparse(version["mirror_url"])

    mirror_dirname = f"openstack-images/{image['shortname']}"
    mirror_filename, mirror_fileextension = os.path.splitext(
        os.path.basename(mirror_path.path)
    )
    _, mirror_fileextension2 = os.path.splitext(mirror_filename)

    if not image["shortname"].startswith(
        ("gardenlinux", "talos", "flatcar", "opnsense")
    ):
        mirror_filename = f"{version['version']}-{image['shortname']}"

    if mirror_fileextension not in [".bz2", ".zip", ".xz", ".gz"]:
        mirror_filename += mirror_fileextension

    if mirror_fileextension2 == ".tar":
        mirror_filename = os.path.basename(mirror_path.path)

    source_filename, source_fileextension = os.path.splitext(
        os.path.basename(source_path.path)
    )
    _, source_fileextension2 = os.path.splitext(source_filename)

    if image["shortname"].startswith(("flatcar")):
        mirror_dirname = os.path.join(mirror_dirname, version["version"])
    elif source_fileextension not in [".bz2", ".zip", ".xz", ".gz"]:
        source_filename += source_fileextension
    else:
        mirror_dirname = os.path.join(mirror_dirname, version["version"])

    if source_fileextension2 == ".tar":
        source_filename = os.path.basename(source_path.path)

    return MirrorPaths(
        mirror_dirname, mirror_filename, source_filename, source_fileextension
    )


def mirror_version(
    client, minio_bucket, image, version, download=True, checksum=True, upload=True
):
    """Mirror one image version into the bucket unless it is already there."""
    logger.debug(f"source: {version['url']}")

    paths = mirror_paths(image, version)
    mirror_dirname = paths.dirname
    mirror_filename = paths.filename
    source_filename = paths.source_filename
    source_fileextension = paths.source_extension

    logger.debug(f"mirror dirname: {mirror_dirname}")
    logger.debug(f"mirror filename: {mirror_filename}")
    logger.debug(f"source filename: {source_filename}")

    # Only a checksum actually verified in this run may be recorded on the
    # object; otherwise a later run would trust bytes nobody checked.
    verified = False

    try:
        client.stat_object(minio_bucket, os.path.join(mirror_dirname, mirror_filename))
        logger.info(f"File {mirror_filename} available in bucket {mirror_dirname}")
        return True
    except S3Error:
        logger.info(
            f"File {mirror_filename} not yet available in bucket {mirror_dirname}"
        )

        if download:
            if not isfile(os.path.basename(source_filename)):
                logger.info(f"File {source_filename} not available on local filesystem")
                logger.info(f"Downloading {version['url']}")
                try:
                    response = requests.get(
                        version["url"],
                        stream=True,
                        allow_redirects=True,
                        timeout=REQUESTS_TIMEOUT,
                    )
                    response.raise_for_status()
                    with open(source_filename, "wb") as fp:
                        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                            fp.write(chunk)
                    del response
                except (requests.RequestException, OSError) as exc:
                    logger.error(f"Download of {version['url']} failed: {exc}")
                    if isfile(source_filename):
                        os.remove(source_filename)
                    return False

            if source_fileextension in [".bz2", ".zip", ".xz", ".gz"]:
                logger.info(f"Decompressing {source_filename}")
                Path("tmp").mkdir(exist_ok=True)
                patoolib.extract_archive(
                    os.path.basename(source_filename), outdir="tmp"
                )
                os.remove(source_filename)
                shutil.copy(os.path.join("tmp", mirror_filename), mirror_filename)
            else:
                os.rename(source_filename, mirror_filename)

            if checksum:
                expected = version.get("checksum")
                if not expected:
                    logger.warning(
                        f"No checksum defined for {mirror_filename}, "
                        "it cannot be verified"
                    )
                else:
                    algorithm, _, expected_digest = expected.partition(":")
                    try:
                        actual_digest = file_checksum(mirror_filename, algorithm)
                    except ValueError:
                        logger.error(
                            f"Cannot verify {mirror_filename}: unknown checksum "
                            f"algorithm {algorithm}"
                        )
                        os.remove(mirror_filename)
                        return False

                    if actual_digest != expected_digest:
                        logger.error(
                            f"{algorithm} of {mirror_filename} is {actual_digest}, "
                            f"the definition says {expected_digest}"
                        )
                        os.remove(mirror_filename)
                        return False

                    logger.info(
                        f"{algorithm} of {mirror_filename} matches the definition"
                    )
                    verified = True

        else:
            logger.info(
                f"Not downloading {source_filename} to local filesystem (download disabled)"
            )

        if upload:
            logger.info(f"Uploading {mirror_filename} to bucket {mirror_dirname}")

            extra = {}
            if verified:
                extra["metadata"] = {UPSTREAM_CHECKSUM_KEY: version["checksum"]}

            client.fput_object(
                minio_bucket,
                os.path.join(mirror_dirname, mirror_filename),
                mirror_filename,
                **extra,
            )

            # Gardenlinux-specific: Upload additional files with simplified filename and SHA256 checksum
            if image["shortname"] == "gardenlinux":
                # Check if filename matches pattern with hash suffix: *-[8-char-hex].qcow2
                hash_pattern = re.compile(r"-([a-f0-9]{8})\.qcow2$")
                match = hash_pattern.search(mirror_filename)

                if match:
                    # Create simplified filename by removing hash suffix
                    simplified_filename = hash_pattern.sub(".qcow2", mirror_filename)
                    logger.info(f"Creating simplified filename: {simplified_filename}")

                    # Create symlink to simplified filename
                    if os.path.exists(simplified_filename):
                        os.remove(simplified_filename)
                    os.symlink(mirror_filename, simplified_filename)

                    # Upload simplified filename
                    logger.info(
                        f"Uploading {simplified_filename} to bucket {mirror_dirname}"
                    )
                    client.fput_object(
                        minio_bucket,
                        os.path.join(mirror_dirname, simplified_filename),
                        simplified_filename,
                    )

                    # Calculate SHA256 checksum
                    h_sha256 = hashlib.sha256()
                    with open(mirror_filename, "rb") as fp:
                        while chunk := fp.read(8192):
                            h_sha256.update(chunk)

                    sha256_hash = h_sha256.hexdigest()
                    logger.info(f"SHA256 of {simplified_filename}: {sha256_hash}")

                    # Create SHA256 checksum file
                    sha256_filename = f"{simplified_filename}.sha256"
                    with open(sha256_filename, "w") as fp:
                        fp.write(f"{sha256_hash}  {simplified_filename}\n")

                    # Upload SHA256 checksum file
                    logger.info(
                        f"Uploading {sha256_filename} to bucket {mirror_dirname}"
                    )
                    client.fput_object(
                        minio_bucket,
                        os.path.join(mirror_dirname, sha256_filename),
                        sha256_filename,
                    )

                    # Clean up temporary files
                    os.remove(simplified_filename)
                    os.remove(sha256_filename)

            os.remove(mirror_filename)
        else:
            logger.info(
                f"Not uploading {mirror_filename} to bucket {mirror_dirname} (upload disabled)"
            )

    return True


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    upload: bool = typer.Option(True, "--upload/--no-upload", help="Upload images"),
    checksum: bool = typer.Option(
        True,
        "--checksum/--no-checksum",
        help="Verify the download against the checksum in the definition",
    ),
    download: bool = typer.Option(
        True, "--download/--no-download", help="Download images"
    ),
    delete: bool = typer.Option(
        True, "--delete/--no-delete", help="Delete images after upload"
    ),
    images: str = typer.Option(
        "etc/images/", help="Path to the directory containing all image files"
    ),
    minio_access_key: str = typer.Option(
        None, help="Minio access key", envvar="MINIO_ACCESS_KEY"
    ),
    minio_secret_key: str = typer.Option(
        None, help="Minio secret key", envvar="MINIO_SECRET_KEY"
    ),
    minio_server: str = typer.Option(
        "nbg1.your-objectstorage.com", help="Minio server"
    ),
    minio_bucket: str = typer.Option("osism", help="Minio bucket"),
):
    if debug:
        level = "DEBUG"
    else:
        level = "INFO"

    log_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<level>{message}</level>"
    )

    logger.remove()
    logger.add(sys.stderr, format=log_fmt, level=level, colorize=True)

    client = Minio(
        minio_server,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
    )

    result = client.bucket_exists(minio_bucket)
    if not result:
        logger.error(f"Create bucket '{minio_bucket}' first")
        sys.exit(1)

    onlyfiles = []
    for f in listdir(images):
        if isfile(join(images, f)):
            logger.debug(f"Adding {f} to the list of files")
            onlyfiles.append(f)

    all_images = []
    for file in [x for x in onlyfiles if x.endswith(".yml")]:
        logger.info(f"Processing file {file}")
        with open(join(images, file)) as fp:
            data = yaml.load(fp, Loader=yaml.SafeLoader)
            for image in data.get("images"):
                logger.debug(f"Adding {image['name']} to the list of images")
                all_images.append(image)

    failed = []

    for image in all_images:
        logger.info(f"Processing image {image['name']}")

        if "versions" not in image:
            continue

        if "shortname" not in image:
            continue

        if not image["shortname"].startswith(
            (
                "almalinux",
                "centos",
                "debian",
                "flatcar",
                "gardenlinux",
                "opnsense",
                "rocky",
                "talos",
                "ubuntu",
            )
        ):
            continue

        for version in image["versions"]:
            if "url" not in version or "mirror_url" not in version:
                continue

            if not mirror_version(
                client,
                minio_bucket,
                image,
                version,
                download=download,
                checksum=checksum,
                upload=upload,
            ):
                failed.append(f"{image['name']} {version['version']}")

    if failed:
        logger.error(f"Failed to mirror {len(failed)} image version(s):")
        for entry in failed:
            logger.error(f"  {entry}")
        sys.exit(1)


if __name__ == "__main__":
    app()
