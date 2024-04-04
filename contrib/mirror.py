# SPDX-License-Identifier: Apache-2.0

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
from urllib.parse import urlparse


app = typer.Typer(add_completion=False)


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not perform any changes"),
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
        "swift.services.a.regiocloud.tech", help="Minio server"
    ),
    minio_bucket: str = typer.Option("openstack-images", help="Minio bucket"),
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
        if not dry_run:
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

        for version in image["versions"]:
            if "source" not in version:
                continue
            else:
                source = version["source"]

            logger.debug(f"source: {source}")

            path = urlparse(source)
            url = urlparse(version["url"])

            dirname = f"{image['shortname']}/{version['version']}"
            filename, fileextension = os.path.splitext(os.path.basename(path.path))
            _, fileextension2 = os.path.splitext(filename)

            if fileextension not in [".bz2", ".zip", ".xz", ".gz"]:
                filename += fileextension

            if fileextension2 == ".tar":
                filename = os.path.basename(url.path)

            logger.debug(f"dirname: {dirname}")
            logger.debug(f"filename: {filename}")

            try:
                client.stat_object(minio_bucket, os.path.join(dirname, filename))
                logger.info(f"File {filename} available in bucket {dirname}")
            except S3Error:
                logger.info(f"File {filename} not yet available in bucket {dirname}")

                if not isfile(os.path.basename(path.path)):
                    logger.info(f"Downloading {version['source']}")
                    response = requests.get(
                        version["source"], stream=True, allow_redirects=True
                    )
                    with open(os.path.basename(path.path), "wb") as fp:
                        shutil.copyfileobj(response.raw, fp)
                    del response

                if fileextension in [".bz2", ".zip", ".xz", ".gz"]:
                    logger.info(f"Decompressing {os.path.basename(path.path)}")
                    patoolib.extract_archive(os.path.basename(path.path), outdir=".")
                    os.remove(os.path.basename(path.path))

                if not dry_run:
                    logger.info(f"Uploading {filename} to bucket {dirname}")
                    client.fput_object(
                        minio_bucket, os.path.join(dirname, filename), filename
                    )
                else:
                    logger.info(
                        f"Not uploading {filename} to bucket {dirname} (dry-run enabled)"
                    )

                os.remove(filename)


if __name__ == "__main__":
    app()
