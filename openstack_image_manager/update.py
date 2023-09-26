# NOTE(berendt): quick & dirty (but it works for the moment)
# source of latest URLs: https://gitlab.com/libosinfo/osinfo-db

from datetime import datetime
import hashlib
import math
import os
import re
import sys
from urllib.parse import urlparse

from loguru import logger
from minio import Minio
from minio.error import S3Error
from natsort import natsorted
import patoolib
import requests
import ruamel.yaml
import typer

app = typer.Typer()
DEBUBU_REGEX = r'<a href="([^"]+)/">(?:release-)?([0-9]+)(\-[0-9]+)?/</a>'


def get_latest_default(shortname, latest_checksum_url, latest_url, checksum_type="sha256"):
    result = requests.get(latest_checksum_url)
    result.raise_for_status()

    latest_filename = os.path.basename(urlparse(latest_url).path)
    filename_pattern = None
    if shortname in ["centos-stream-8", "centos-stream-9", "centos-7"]:
        filename_pattern = latest_filename.replace("HEREBE", "")
        filename_pattern = filename_pattern.replace("DRAGONS", "")

    checksums = {}
    for line in result.text.split("\n"):
        cs = re.split("\s+", line)  # noqa W605
        if shortname in ["rocky-8", "rocky-9"]:
            if len(cs) == 4 and cs[0] == "SHA256":
                checksums[latest_filename] = cs[3]
        elif shortname in ["centos-7"]:
            if len(cs) == 2 and re.search(filename_pattern, cs[1]):
                checksums[cs[1]] = cs[0]
        elif shortname in ["centos-stream-8", "centos-stream-9"]:
            if len(cs) == 4 and cs[0] == "SHA256" and re.search(
                filename_pattern, cs[1][1:-1]
            ):
                checksums[cs[1][1:-1]] = cs[3]
        else:
            if len(cs) == 2:
                checksums[cs[1]] = cs[0]

    if filename_pattern:
        new_latest_filename = natsorted(checksums.keys())[-1]
        new_latest_url = latest_url.replace(latest_filename, new_latest_filename)

        logger.info(f"Latest URL is now {new_latest_url}")
        logger.info(f"Latest filename is now {new_latest_filename}")

        latest_filename = new_latest_filename
        latest_url = new_latest_url

    current_checksum = f"{checksum_type}:{checksums[latest_filename]}"
    return current_checksum, latest_url, None


def resolve_debubu(base_url, rex=re.compile(DEBUBU_REGEX)):
    result = requests.get(base_url)
    result.raise_for_status()
    latest_folder, latest_date, latest_build = sorted(rex.findall(result.text))[-1]
    return latest_folder, latest_date, latest_build


def get_latest_debubu(shortname, latest_checksum_url, latest_url, checksum_type=None):
    base_url, _, filename = latest_url.rsplit("/", 2)
    latest_folder, latest_date, latest_build = resolve_debubu(base_url)
    current_base_url = f"{base_url}/{latest_folder}"
    current_checksum_url = f"{current_base_url}/{latest_checksum_url.rsplit('/', 1)[-1]}"
    result = requests.get(current_checksum_url)
    result.raise_for_status()
    current_checksum = None
    current_filename = filename
    if latest_build:  # Debian includes date-build in file name
        fn_pre, fn_suf = filename.rsplit('.', 1)
        current_filename = f"{fn_pre}-{latest_date}{latest_build}.{fn_suf}"
    for line in result.text.splitlines():
        cs = line.split()
        if len(cs) != 2:
            continue
        if cs[1].startswith("*"):  # Ubuntu has the asterisk in front of the name
            cs[1] = cs[1][1:]
        if cs[1] != current_filename:
            continue
        if checksum_type is None:  # use heuristics to distinguish sha256/sha512
            checksum_type = "sha256" if len(cs[0]) == 64 else "sha512"
        current_checksum = f"{checksum_type}:{cs[0]}"
        break
    if current_checksum is None:
        raise RuntimeError(f"{current_checksum_url} does not contain {current_filename}")
    current_url = f"{current_base_url}/{current_filename}"
    return current_checksum, current_url, latest_date


IMAGES = {
    "almalinux": get_latest_default,
    "centos": get_latest_default,
    "debian": get_latest_debubu,
    "rockylinux": get_latest_default,
    "ubuntu": get_latest_debubu,
}


def mirror_image(
    image, extracted_file, minio_server, minio_bucket, minio_access_key, minio_secret_key
):
    client = Minio(
        minio_server,
        access_key=minio_access_key,
        secret_key=minio_secret_key,
    )

    version = image["versions"][0]
    dirname = image["shortname"]
    shortname = image["shortname"]
    format = image["format"]
    new_version = version["version"]
    new_filename = f"{new_version}-{shortname}.{format}"

    try:
        client.stat_object(minio_bucket, os.path.join(dirname, new_filename))
        logger.info("'%s' available in '%s'" % (new_filename, dirname))
    except S3Error:
        logger.info("'%s' not yet available in '%s'" % (new_filename, dirname))

        logger.info(
            "Uploading '%s' to '%s' as '%s'" % (extracted_file, dirname, new_filename)
        )

        client.fput_object(minio_bucket, os.path.join(dirname, new_filename), extracted_file)


def size_clean(size):
    size_name = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    i = int(math.floor(math.log(size, 1024)))
    s = size / 1024 ** i
    return f"{s:.2f} {size_name[i]}"


def download_and_hash(download_url: str):
    path = urlparse(download_url)
    filename, fileextension = os.path.splitext(os.path.basename(path.path))
    is_archive = fileextension in [".bz2", ".zip", ".xz", ".gz"]
    if not is_archive:
        filename += fileextension
    download_filename = os.path.basename(path.path)
    http_headers = None
    hash_obj = hashlib.new("sha512")

    with requests.get(url=download_url, stream=True, timeout=30) as response:
        if response.status_code != 200:
            logger.error(f"Downloading image '{download_url}' failed with error code {response.status_code}")
            return None, None, None

        http_headers = response.headers
        file_size = int(http_headers["Content-Length"])
        logger.info(f"Image size {size_clean(file_size)}")

        downloadedBytes = 0
        lastProgress = 0
        with open(download_filename, "wb") as fp:
            for chunk in response.iter_content(chunk_size=8192):
                downloadedBytes += 8192
                progressPercent = (downloadedBytes / file_size) * 100
                progress = round(min(max(progressPercent, 0), 100))
                if progress - lastProgress >= 5:
                    logger.info(f"Downloading image: {progress}%")
                    lastProgress = progress

                fp.write(chunk)

                if not is_archive:
                    hash_obj.update(chunk)

    if not is_archive:
        sha512 = hash_obj.hexdigest()
        return http_headers, f"sha512:{sha512}", download_filename
    else:
        assert download_filename not in ["", ".", " ", "/", ".."]
        logger.info("Decompressing '%s'" % download_filename)
        patoolib.extract_archive(download_filename, outdir=".")
        os.remove(download_filename)

        with open(filename, 'rb') as fp:
            chunk = fp.read(8192)
            while chunk:
                hash_obj.update(chunk)
                chunk = fp.read(8192)

        sha512 = hash_obj.hexdigest()
        return http_headers, f"sha512:{sha512}", filename


def update_image(image, getter, minio_server, minio_bucket, minio_access_key, minio_secret_key):
    name = image["name"]
    logger.info(f"Checking image {name}")

    latest_url = image["latest_url"]
    logger.info(f"Latest download URL is {latest_url}")

    latest_checksum_url = image["latest_checksum_url"]
    logger.info(f"Getting checksums from {latest_checksum_url}")

    shortname = image["shortname"]
    current_checksum, current_url, current_version = getter(shortname, latest_checksum_url, latest_url)

    logger.info(f"Checksum of current {current_url.rsplit('/', 1)[-1]} is {current_checksum}")

    if not image["versions"]:
        logger.info("No image available so far")
        image["versions"].append(
            {
                "build_date": None,
                "checksum": None,
                "url": None,
                "version": None,
                "verify_checksum": None,
            }
        )

    latest_checksum = image["versions"][0]["checksum"]
    logger.info(f"Our checksum is {latest_checksum}")

    if latest_checksum == current_checksum:
        logger.info(f"Image {name} is up-to-date, nothing to do")
        return 0

    logger.info(f"Image {name} change detected. Downloading Image...")

    headers, verify_checksum, extracted_file = download_and_hash(current_url)
    if verify_checksum is None or extracted_file in ["", ".", " ", "/", ".."]:
        logger.error(f"Downloading and hashing {name} failed")
        return 0

    logger.info(f"Image {name} has the verification checksum {verify_checksum}")

    if current_version is None:
        logger.info("Using HTTP 'last-modified' header as current version")

        dt = datetime.strptime(
            headers["last-modified"], "%a, %d %b %Y %H:%M:%S %Z"
        )
        current_version = dt.strftime("%Y%m%d")

    new_values = {
        "version": current_version,
        "build_date": datetime.strptime(current_version, "%Y%m%d").date(),
        "checksum": current_checksum,
        "url": current_url,
        "verify_checksum": verify_checksum,
    }
    logger.info(f"New values are {new_values}")
    image["versions"][0].update(new_values)

    shortname = image["shortname"]
    format = image["format"]

    minio_server = str(minio_server)
    minio_bucket = str(minio_bucket)
    new_url = f"https://{minio_server}/{minio_bucket}/{shortname}/{current_version}-{shortname}.{format}"
    logger.info(f"New URL is {new_url}")
    image["versions"][0]["mirror_url"] = new_url

    mirror_image(
        image,
        extracted_file,
        minio_server,
        minio_bucket,
        minio_access_key,
        minio_secret_key,
    )

    os.remove(extracted_file)

    return 1


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

        updates = 0
        for index, image in enumerate(data["images"]):
            if "latest_url" not in image:
                continue
            updates += update_image(
                image,
                getter,
                minio_server,
                minio_bucket,
                minio_access_key,
                minio_secret_key,
            )

        if not updates:
            continue
        with open(p, "w+") as fp:
            ryaml.explicit_start = True
            ryaml.indent(sequence=4, offset=2)
            ryaml.dump(data, fp)


if __name__ == "__main__":
    app()
