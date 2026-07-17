# SPDX-License-Identifier: Apache-2.0

# source of latest URLs: https://gitlab.com/libosinfo/osinfo-db

from dataclasses import dataclass
from datetime import datetime
import os
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen

from loguru import logger
from natsort import natsorted
import requests
import ruamel.yaml
import typer

app = typer.Typer()
DEBUBU_REGEX = r'<a href="([^"]+)/">(?:release-)?([0-9]+)(\-[0-9]+)?/</a>'
HTTP_TIMEOUT = 30
MIRROR_BASE_URL = os.environ.get(
    "MIRROR_BASE_URL",
    "https://nbg1.your-objectstorage.com/osism/openstack-images",
).rstrip("/")


@dataclass
class MirrorDirConfig:
    # "plain" -> `<hash> <filename>` ; "bsd" -> `SHA256 (<filename>) = <hash>`
    checksum_style: str = "plain"
    # resolve newest build from the manifest via the HEREBE/DRAGONS placeholder pattern
    resolve_latest: bool = False
    # for bsd: "filename" keys on the parenthesised name; "target" maps every
    # SHA256 line onto the known latest filename (last line wins)
    bsd_key: str = "filename"


DEFAULT_MIRROR_CONFIG = MirrorDirConfig()
MIRROR_DIR_CONFIG = {
    "centos-7": MirrorDirConfig(checksum_style="plain", resolve_latest=True),
    "centos-stream-8": MirrorDirConfig(checksum_style="bsd", resolve_latest=True),
    "centos-stream-9": MirrorDirConfig(checksum_style="bsd", resolve_latest=True),
    "rocky-8": MirrorDirConfig(checksum_style="bsd", bsd_key="target"),
    "rocky-9": MirrorDirConfig(checksum_style="bsd", bsd_key="target"),
}


class MirrorDirHandler:
    def resolve(self, image: dict) -> tuple[str, str, str | None]:
        shortname = image["shortname"]
        latest_url = image["latest_url"]
        cfg = MIRROR_DIR_CONFIG.get(shortname, DEFAULT_MIRROR_CONFIG)

        result = requests.get(image["latest_checksum_url"], timeout=HTTP_TIMEOUT)
        result.raise_for_status()

        original_filename = os.path.basename(urlparse(latest_url).path)
        pattern = None
        if cfg.resolve_latest:
            pattern = original_filename.replace("HEREBE", "").replace("DRAGONS", "")

        checksums = {}
        for line in result.text.split("\n"):
            cs = re.split(r"\s+", line)
            if cfg.checksum_style == "bsd":
                if len(cs) == 4 and cs[0] == "SHA256":
                    if cfg.bsd_key == "target":
                        checksums[original_filename] = cs[3]
                    else:
                        name = cs[1][1:-1]
                        if pattern is None or re.search(pattern, name):
                            checksums[name] = cs[3]
            else:
                if len(cs) == 2:
                    if pattern is None or re.search(pattern, cs[1]):
                        checksums[cs[1]] = cs[0]

        target_filename = original_filename
        if pattern:
            target_filename = natsorted(checksums.keys())[-1]
            latest_url = latest_url.replace(original_filename, target_filename)

        return f"sha256:{checksums[target_filename]}", latest_url, None


class DirListingHandler:
    def resolve(self, image: dict) -> tuple[str, str, str | None]:
        latest_url = image["latest_url"]
        latest_checksum_url = image["latest_checksum_url"]
        base_url, _, filename = latest_url.rsplit("/", 2)

        listing = requests.get(base_url, timeout=HTTP_TIMEOUT)
        listing.raise_for_status()
        latest_folder, latest_date, latest_build = sorted(
            re.compile(DEBUBU_REGEX).findall(listing.text)
        )[-1]

        current_base_url = f"{base_url}/{latest_folder}"
        current_checksum_url = (
            f"{current_base_url}/{latest_checksum_url.rsplit('/', 1)[-1]}"
        )
        result = requests.get(current_checksum_url, timeout=HTTP_TIMEOUT)
        result.raise_for_status()

        current_filename = filename
        if latest_build:
            fn_pre, fn_suf = filename.rsplit(".", 1)
            current_filename = f"{fn_pre}-{latest_date}{latest_build}.{fn_suf}"

        for line in result.text.splitlines():
            cs = line.split()
            if len(cs) != 2:
                continue
            if cs[1].startswith("*"):
                cs[1] = cs[1][1:]
            if cs[1] != current_filename:
                continue
            checksum_type = "sha256" if len(cs[0]) == 64 else "sha512"
            return (
                f"{checksum_type}:{cs[0]}",
                f"{current_base_url}/{current_filename}",
                latest_date,
            )

        raise RuntimeError(
            f"{current_checksum_url} does not contain {current_filename}"
        )


HANDLERS = {
    "almalinux": MirrorDirHandler(),
    "centos": MirrorDirHandler(),
    "debian": DirListingHandler(),
    "rockylinux": MirrorDirHandler(),
    "ubuntu": DirListingHandler(),
}


def update_image(image, handler):
    name = image["name"]
    shortname = image["shortname"]
    logger.info(f"Checking image {name}")

    current_checksum, current_url, current_version = handler.resolve(image)
    logger.info(
        f"Checksum of current {current_url.rsplit('/', 1)[-1]} is {current_checksum}"
    )

    if not image["versions"]:
        logger.info("No image available so far")
        image["versions"].append(
            {"build_date": None, "checksum": None, "url": None, "version": None}
        )

    if image["versions"][0]["checksum"] == current_checksum:
        logger.info(f"Image {name} is up-to-date, nothing to do")
        return 0

    if current_version is None:
        logger.info(f"Checking {current_url}")
        try:
            conn = urlopen(current_url, timeout=HTTP_TIMEOUT)
        except HTTPError as e:
            logger.warning(f"Image {name} cannot be processed, skipping: {e}")
            return 0
        dt = datetime.strptime(
            conn.headers["last-modified"], "%a, %d %b %Y %H:%M:%S %Z"
        )
        current_version = dt.strftime("%Y%m%d")

    image_format = image["format"]
    mirror_url = (
        f"{MIRROR_BASE_URL}/{shortname}/"
        f"{current_version}-{shortname}.{image_format}"
    )
    logger.info(f"New URL is {mirror_url}")

    image["versions"][0].update(
        {
            "version": current_version,
            "build_date": datetime.strptime(current_version, "%Y%m%d").date(),
            "checksum": current_checksum,
            "url": current_url,
            "mirror_url": mirror_url,
        }
    )
    return 1


@app.command()
def main(
    name: str = typer.Option(
        None, "--name", help="Only update the image with this name"
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Compute updates but do not write the YAML files"
    ),
    images_dir: str = typer.Option(
        "etc/images", "--images-dir", help="Directory with the image definition files"
    ),
):
    if debug:
        level = "DEBUG"
    else:
        level = "INFO"

    logger.remove()
    log_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add(sys.stderr, format=log_fmt, level=level, colorize=True)

    for image_name, handler in HANDLERS.items():
        if name and image_name != name:
            logger.info(f"Skipping {image_name}")
            continue

        p = os.path.join(images_dir, f"{image_name}.yml")
        logger.info(f"Processing file {p}")

        ryaml = ruamel.yaml.YAML()
        with open(p) as fp:
            data = ryaml.load(fp)

        updates = 0
        for image in data["images"]:
            if "latest_url" not in image:
                continue
            updates += update_image(image, handler)

        if not updates:
            continue

        if dry_run:
            logger.info(f"Dry-run enabled, not writing {p}")
            continue

        with open(p, "w+") as fp:
            ryaml.explicit_start = True
            ryaml.indent(sequence=4, offset=2)
            ryaml.dump(data, fp)


if __name__ == "__main__":
    app()
