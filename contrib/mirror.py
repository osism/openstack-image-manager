# SPDX-License-Identifier: Apache-2.0

import hashlib
import os
import patoolib
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
from urllib.parse import urlparse


app = typer.Typer(add_completion=False)


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    upload: bool = typer.Option(True, "--upload/--no-upload", help="Upload images"),
    checksum: bool = typer.Option(
        True, "--checksum/--no-checksum", help="Calculate and compare the checksum"
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

            logger.debug(f"source: {version['url']}")

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

            logger.debug(f"mirror dirname: {mirror_dirname}")
            logger.debug(f"mirror filename: {mirror_filename}")

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

            logger.debug(f"source filename: {source_filename}")

            try:
                client.stat_object(
                    minio_bucket, os.path.join(mirror_dirname, mirror_filename)
                )
                logger.info(
                    f"File {mirror_filename} available in bucket {mirror_dirname}"
                )
            except S3Error:
                logger.info(
                    f"File {mirror_filename} not yet available in bucket {mirror_dirname}"
                )

                if download:
                    if not isfile(os.path.basename(source_filename)):
                        logger.info(
                            f"File {source_filename} not available on local filesystem"
                        )
                        logger.info(f"Downloading {version['url']}")
                        response = requests.get(
                            version["url"], stream=True, allow_redirects=True
                        )
                        with open(source_filename, "wb") as fp:
                            shutil.copyfileobj(response.raw, fp)
                        del response

                    if source_fileextension in [".bz2", ".zip", ".xz", ".gz"]:
                        logger.info(f"Decompressing {source_filename}")
                        Path("tmp").mkdir(exist_ok=True)
                        patoolib.extract_archive(
                            os.path.basename(source_filename), outdir="tmp"
                        )
                        os.remove(source_filename)
                        shutil.copy(
                            os.path.join("tmp", mirror_filename), mirror_filename
                        )
                    else:
                        os.rename(source_filename, mirror_filename)

                    if checksum:
                        h = hashlib.new("sha512")
                        with open(mirror_filename, "rb") as fp:
                            while c := fp.read(8192):
                                h.update(c)

                        logger.info(f"SHA512 of {mirror_filename}: {h.hexdigest()}")

                else:
                    logger.info(
                        f"Not downloading {source_filename} to local filesystem (download disabled)"
                    )

                if upload:
                    logger.info(
                        f"Uploading {mirror_filename} to bucket {mirror_dirname}"
                    )

                    client.fput_object(
                        minio_bucket,
                        os.path.join(mirror_dirname, mirror_filename),
                        mirror_filename,
                    )

                    os.remove(mirror_filename)
                else:
                    logger.info(
                        f"Not uploading {mirror_filename} to bucket {mirror_dirname} (upload disabled)"
                    )


if __name__ == "__main__":
    app()
