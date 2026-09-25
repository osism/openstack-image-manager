#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
Add the os_distro values known to libosinfo to etc/schema.yaml.

The os_distro property holds a libosinfo <distro> value. This script collects
every <distro> value in osinfo-db and reports those missing from the os_distro
enum in the schema; with --write it adds them. Values are only ever added, so
the values documented for Glance and the local additions in the enum are kept.
"""

import io
import re
import sys
import tarfile

import requests
import typer
from loguru import logger

app = typer.Typer()

HTTP_TIMEOUT = 30
OSINFO_DB_ARCHIVE_URL = (
    "https://gitlab.com/libosinfo/osinfo-db/-/archive/main/"
    "osinfo-db-main.tar.gz?path=data/os"
)
SCHEMA_PATH = "etc/schema.yaml"
DISTRO_REGEX = re.compile(r"<distro>\s*([^<\s]+)\s*</distro>")
ENUM_REGEX = re.compile(r"^(?P<prefix>\s*os_distro: enum\()(?P<values>[^)]*)\)$", re.M)


def extract_distros(archive: bytes) -> set[str]:
    """Return the lowercased <distro> values in an osinfo-db tarball."""
    distros: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".xml.in"):
                continue
            fp = tar.extractfile(member)
            if fp is None:
                continue
            content = fp.read().decode("utf-8")
            distros.update(d.lower() for d in DISTRO_REGEX.findall(content))
    return distros


def fetch_osinfo_distros() -> set[str]:
    """Download osinfo-db and return its lowercased <distro> values."""
    response = requests.get(OSINFO_DB_ARCHIVE_URL, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return extract_distros(response.content)


def read_schema_distros(schema: str) -> set[str]:
    """Return the values of the os_distro enum in the schema text."""
    match = ENUM_REGEX.search(schema)
    if not match:
        raise ValueError("No os_distro enum found in the schema")
    return set(re.findall(r"'([^']*)'", match.group("values")))


def write_schema_distros(schema: str, distros: set[str]) -> str:
    """Return the schema text with the os_distro enum set to the sorted values."""
    values = ", ".join(f"'{d}'" for d in sorted(distros))
    return ENUM_REGEX.sub(lambda m: f"{m.group('prefix')}{values})", schema, count=1)


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    write: bool = typer.Option(
        False, "--write", help="Add the missing values to the schema"
    ),
    schema_path: str = typer.Option(
        SCHEMA_PATH, "--schema", help="Path to the schema file"
    ),
):
    """
    Report (or, with --write, add) osinfo-db distros missing from the schema.
    """
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

    with open(schema_path) as fp:
        schema = fp.read()
    known = read_schema_distros(schema)

    try:
        osinfo = fetch_osinfo_distros()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch osinfo-db: {e}")
        raise typer.Exit(2)
    logger.debug(f"osinfo-db knows {len(osinfo)} distros")

    missing = osinfo - known
    if not missing:
        logger.info("The schema contains every osinfo-db distro")
        return

    logger.info(f"Missing from the schema: {', '.join(sorted(missing))}")
    if not write:
        raise typer.Exit(1)

    with open(schema_path, "w") as fp:
        fp.write(write_schema_distros(schema, known | missing))
    logger.info(f"Added {len(missing)} values to {schema_path}")


if __name__ == "__main__":
    app()
