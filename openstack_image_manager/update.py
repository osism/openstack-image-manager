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
from natsort import natsorted
import patoolib
import requests
import ruamel.yaml
import typer

app = typer.Typer()


def get_latest_default(shortname, latest_checksum_url, latest_url):
    parsed_url = urlparse(latest_url)
    latest_filename = os.path.basename(parsed_url.path)

    result = requests.get(latest_checksum_url)

    checksums = {}

    checksum_type = "sha256"
    filename_pattern = None

    if shortname in ["centos-stream-8", "centos-stream-9", "centos-7"]:
        filename_pattern = latest_filename.replace("HEREBE", "")
        filename_pattern = filename_pattern.replace("DRAGONS", "")
    elif shortname in ["debian-10", "debian-11", "debian-12"]:
        checksum_type = "sha512"

    for line in result.text.split("\n"):
        if shortname in ["rocky-8", "rocky-9"]:
            splitted_line = re.split("\s+", line)  # noqa W605
            if splitted_line[0] == "SHA256":
                checksums[latest_filename] = splitted_line[3]
        elif shortname in [
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
        elif shortname in ["centos-7"]:
            splitted_line = re.split("\s+", line)  # noqa W605
            if len(splitted_line) == 2:
                if re.search(filename_pattern, splitted_line[1]):
                    checksums[splitted_line[1]] = splitted_line[0]
        elif shortname in ["centos-stream-8", "centos-stream-9"]:
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
    return current_checksum, latest_url


IMAGES = {
    "almalinux": get_latest_default,
    "centos": get_latest_default,
    "debian": get_latest_default, 
    "rockylinux": get_latest_default, 
    "ubuntu": get_latest_default,
}


def mirror_image(
    image, latest_url, minio_server, minio_bucket, minio_access_key, minio_secret_key
):
    client = Minio(
        minio_server,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
    )

    version = image["versions"][0]
    version["source"] = latest_url

    path = urlparse(version["source"])
    dirname = image["shortname"]
    filename, fileextension = os.path.splitext(os.path.basename(path.path))

    if fileextension not in [".bz2", ".zip", ".xz", ".gz"]:
        filename += fileextension

    shortname = image["shortname"]
    format = image["format"]
    new_version = version["version"]
    new_filename = f"{new_version}-{shortname}.{format}"

    try:
        client.stat_object(minio_bucket, os.path.join(dirname, new_filename))
        logger.info("'%s' available in '%s'" % (new_filename, dirname))
    except S3Error:
        logger.info("'%s' not yet available in '%s'" % (new_filename, dirname))
        logger.info("Downloading '%s'" % version["source"])
        response = requests.get(version["source"], stream=True)
        with open(os.path.basename(path.path), "wb") as fp:
            shutil.copyfileobj(response.raw, fp)
        del response

        if fileextension in [".bz2", ".zip", ".xz", ".gz"]:
            logger.info("Decompressing '%s'" % os.path.basename(path.path))
            patoolib.extract_archive(os.path.basename(path.path), outdir=".")
            os.remove(os.path.basename(path.path))

        logger.info(
            "Uploading '%s' to '%s' as '%s'" % (filename, dirname, new_filename)
        )

        client.fput_object(minio_bucket, os.path.join(dirname, new_filename), filename)
        os.remove(filename)


def update_image(image, getter, minio_server, minio_bucket, minio_access_key, minio_secret_key):
    name = image["name"]
    logger.info(f"Checking image {name}")

    latest_url = image["latest_url"]
    logger.info(f"Latest download URL is {latest_url}")

    latest_checksum_url = image["latest_checksum_url"]
    logger.info(f"Getting checksums from {latest_checksum_url}")
    
    shortname = image["shortname"]
    current_checksum, current_url = getter(shortname, latest_checksum_url, latest_url)

    logger.info(f"Checksum of current {current_url.rsplit('/', 1)[-1]} is {current_checksum}")

    if not image["versions"]:
        logger.info("No image available so far")
        image["versions"].append(
            {
                "build_date": None,
                "checksum": None,
                "url": None,
                "version": None,
            }
        )

    latest_checksum = image["versions"][0]["checksum"]
    logger.info(f"Our checksum is {latest_checksum}")

    if latest_checksum == current_checksum:
        logger.info(f"Image {name} is up-to-date, nothing to do")
        return

    logger.info(f"Checking {current_url}")

    conn = urlopen(current_url, timeout=30)
    struct = time.strptime(
        conn.headers["last-modified"], "%a, %d %b %Y %H:%M:%S %Z"
    )
    dt = datetime.fromtimestamp(time.mktime(struct))

    new_version = dt.strftime("%Y%m%d")
    logger.info(f"New version is {new_version}")
    image["versions"][0]["version"] = new_version

    new_build_date = dt.strftime("%Y-%m-%d")
    logger.info(f"New build date is {new_build_date}")
    image["versions"][0]["build_date"] = dt.date()

    logger.info(f"New checksum is {current_checksum}")
    image["versions"][0]["checksum"] = current_checksum

    shortname = image["shortname"]
    format = image["format"]

    minio_server = str(minio_server)
    minio_bucket = str(minio_bucket)
    new_url = f"https://{minio_server}/{minio_bucket}/{shortname}/{new_version}-{shortname}.{format}"
    logger.info(f"New URL is {new_url}")
    image["versions"][0]["mirror_url"] = new_url
    image["versions"][0]["url"] = current_url

    mirror_image(
        image,
        latest_url,
        minio_server,
        minio_bucket,
        minio_access_key,
        minio_secret_key,
    )
    del image["versions"][0]["source"]


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
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

    logger.remove()  # remove the default sink
    log_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add(sys.stderr, format=log_fmt, level=level, colorize=True)

    for image, getter in IMAGES.items():
        p = f"etc/images/{image}.yml"

        ryaml = ruamel.yaml.YAML()
        with open(p) as fp:
            data = ryaml.load(fp)

        for index, image in enumerate(data["images"]):
            if "latest_url" in image:
                update_image(
                    image,
                    getter,
                    minio_server,
                    minio_bucket,
                    minio_access_key,
                    minio_secret_key,
                )

        with open(p, "w+") as fp:
            ryaml.explicit_start = True
            ryaml.indent(sequence=4, offset=2)
            ryaml.dump(data, fp)


if __name__ == "__main__":
    app()
