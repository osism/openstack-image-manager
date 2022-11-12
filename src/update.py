# NOTE(berendt): quick & dirty (but it works for the moment)
# source of latest URLs: https://gitlab.com/libosinfo/osinfo-db

from datetime import datetime
import os
import re
import shutil
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from loguru import logger
from minio import Minio
from minio.error import S3Error
from munch import Munch
from natsort import natsorted
import patoolib
import requests
import ruamel.yaml
import typer
import yaml

app = typer.Typer()


def mirror_image(image, latest_url, CONF):
    client = Minio(
        CONF.minio_server,
        access_key=CONF.minio_access_key,
        secret_key=CONF.minio_secret_key,
    )

    version = image["versions"][0]
    version["source"] = latest_url

    path = urlparse(version["source"])
    dirname = image["shortname"]
    filename, fileextension = os.path.splitext(os.path.basename(path.path))

    if fileextension not in [".bz2", ".zip", ".xz"]:
        filename += fileextension

    shortname = image["shortname"]
    format = image["format"]
    new_version = version["version"]
    new_filename = f"{new_version}-{shortname}.{format}"

    try:
        client.stat_object(CONF.minio_bucket, os.path.join(dirname, new_filename))
        logger.info("'%s' available in '%s'" % (new_filename, dirname))
    except S3Error:
        logger.info("'%s' not yet available in '%s'" % (new_filename, dirname))
        logger.info("Downloading '%s'" % version["source"])
        response = requests.get(version["source"], stream=True)
        with open(os.path.basename(path.path), "wb") as fp:
            shutil.copyfileobj(response.raw, fp)
        del response

        if fileextension in [".bz2", ".zip", ".xz"]:
            logger.info("Decompressing '%s'" % os.path.basename(path.path))
            patoolib.extract_archive(os.path.basename(path.path), outdir=".")
            os.remove(os.path.basename(path.path))

        logger.info(
            "Uploading '%s' to '%s' as '%s'" % (filename, dirname, new_filename)
        )

        client.fput_object(
            CONF.minio_bucket, os.path.join(dirname, new_filename), filename
        )
        os.remove(filename)


def update_image(image, CONF):
    name = image["name"]
    logger.info(f"Checking image {name}")

    latest_url = image["latest_url"]
    logger.info(f"Latest download URL is {latest_url}")

    parsed_url = urlparse(latest_url)
    latest_filename = os.path.basename(parsed_url.path)

    latest_checksum_url = image["latest_checksum_url"]
    logger.info(f"Getting checksums from {latest_checksum_url}")

    result = requests.get(latest_checksum_url)
    checksums = {}

    checksum_type = "sha256"
    filename_pattern = None

    if image["shortname"] in ["centos-stream-8", "centos-stream-9", "centos-7"]:
        filename_pattern = latest_filename.replace("HEREBE", "")
        filename_pattern = filename_pattern.replace("DRAGONS", "")
    elif image["shortname"] in ["debian-10", "debian-11"]:
        checksum_type = "sha512"

    for line in result.text.split("\n"):
        if image["shortname"] == "rocky-9":
            splitted_line = re.split("\s+", line)  # noqa W605
            if splitted_line[0] == "SHA256":
                checksums[latest_filename] = splitted_line[3]
        elif image["shortname"] in [
            "ubuntu-14.04",
            "ubuntu-16.04",
            "ubuntu-16.04-minimal",
            "ubuntu-18.04",
            "ubuntu-18.04-minimal",
            "ubuntu-20.04",
            "ubuntu-20.04-minimal",
            "ubuntu-22.04",
            "ubuntu-22.04-minimal",
        ]:
            splitted_line = re.split("\s+", line)  # noqa W605
            if len(splitted_line) == 2:
                checksums[splitted_line[1][1:]] = splitted_line[0]
        elif image["shortname"] in ["centos-7"]:
            splitted_line = re.split("\s+", line)  # noqa W605
            if len(splitted_line) == 2:
                if re.search(filename_pattern, splitted_line[1]):
                    checksums[splitted_line[1]] = splitted_line[0]
        elif image["shortname"] in ["centos-stream-8", "centos-stream-9"]:
            splitted_line = re.split("\s+", line)  # noqa W605
            if splitted_line[0] == "SHA256" and re.search(
                filename_pattern, splitted_line[1][1:-1]
            ):
                checksums[splitted_line[1][1:-1]] = splitted_line[3]
        else:
            splitted_line = re.split("\s+", line)  # noqa W605
            if len(splitted_line) == 2:
                checksums[splitted_line[1]] = splitted_line[0]

    if filename_pattern:
        new_latest_filename = natsorted(checksums.keys())[-1]
        new_latest_url = latest_url.replace(latest_filename, new_latest_filename)

        logger.info(f"Latest URL is now {new_latest_url}")
        logger.info(f"Latest filename is now {new_latest_filename}")

        latest_filename = new_latest_filename
        latest_url = new_latest_url

    current_checksum = f"{checksum_type}:{checksums[latest_filename]}"
    logger.info(f"Checksum of current {latest_filename} is {current_checksum}")

    latest_version = image["versions"][0]
    latest_checksum = latest_version["checksum"]
    logger.info(f"Our checksum is {latest_checksum}")

    if latest_checksum != current_checksum:
        logger.info(f"Checking {latest_url}")

        conn = urlopen(latest_url, timeout=30)
        struct = time.strptime(
            conn.headers["last-modified"], "%a, %d %b %Y %H:%M:%S %Z"
        )
        dt = datetime.fromtimestamp(time.mktime(struct))

        new_version = dt.strftime("%Y%m%d")
        logger.info(f"New version is {new_version}")
        image["versions"][0]["version"] = new_version

        new_build_date = dt.strftime("%Y-%m-%d")
        logger.info(f"New build date is {new_build_date}")
        image["versions"][0]["build_date"] = new_build_date

        logger.info(f"New checksum is {current_checksum}")
        image["versions"][0]["checksum"] = current_checksum

        shortname = image["shortname"]
        format = image["format"]

        minio_server = str(CONF.minio_server)
        minio_bucket = str(CONF.minio_bucket)
        new_url = f"https://{minio_server}/{minio_bucket}/{shortname}/{new_version}-{shortname}.{format}"
        logger.info(f"New URL is {new_url}")
        image["versions"][0]["url"] = new_url

        mirror_image(image, latest_url, CONF)
        del image["versions"][0]["source"]

    else:
        logger.info(f"Image {name} is up-to-date, nothing to do")

    return image


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    image: str = typer.Option("almalinux", help="Image to update"),
    minio_access_key: str = typer.Option(None, help="Minio access key"),
    minio_secret_key: str = typer.Option(None, help="Minio secret key"),
    minio_server: str = typer.Option("minio.services.osism.tech", help="Minio server"),
    minio_bucket: str = typer.Option("openstack-image-manager", help="Minio bucket"),
):

    CONF = Munch.fromDict(locals())

    if CONF.debug:
        level = "DEBUG"
    else:
        level = "INFO"

    logger.remove()  # remove the default sink
    log_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add(sys.stderr, format=log_fmt, level=level, colorize=True)

    p = f"etc/images/{image}.yml"

    with open(p) as fp:
        data = yaml.safe_load(fp)

    for index, image in enumerate(data["images"]):
        if "latest_url" in image:
            updated_image = update_image(image, CONF)
            data["images"][index] = updated_image

    with open(p, "w+") as fp:
        ryaml = ruamel.yaml.YAML()
        ryaml.explicit_start = True
        ryaml.indent(sequence=4, offset=2)
        ryaml.dump(data, fp)


if __name__ == "__main__":
    app()
