#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
Update gardenlinux.yml with new versions from GitHub releases.

This script checks the GitHub releases feed for gardenlinux/gardenlinux
and adds new OpenStack image versions to etc/images/gardenlinux.yml.
"""

import hashlib
import os
import re
import shutil
import sys
from datetime import datetime
from typing import Optional

import patoolib
import requests
import ruamel.yaml
import typer
from loguru import logger

app = typer.Typer()

GITHUB_API_URL = "https://api.github.com/repos/gardenlinux/gardenlinux/releases"
GARDENLINUX_YML_PATH = "etc/images/gardenlinux.yml"
MINIO_SERVER = "nbg1.your-objectstorage.com"
MINIO_BUCKET = "osism/openstack-images"


def get_latest_releases(max_releases: int = 10) -> list:
    """
    Fetch latest releases from GitHub API.

    Args:
        max_releases: Maximum number of releases to fetch

    Returns:
        List of release objects
    """
    try:
        response = requests.get(
            GITHUB_API_URL, params={"per_page": max_releases}, timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch releases from GitHub: {e}")
        return []


def extract_openstack_image(release: dict) -> Optional[dict]:
    """
    Extract OpenStack gardener_prod image information from a release.

    Args:
        release: GitHub release object

    Returns:
        Dictionary with version, url, and build_date, or None if not found
        Note: checksum is NOT included here - it must be calculated separately
    """
    version = release["tag_name"]
    published_at = release.get("published_at")

    if not published_at:
        logger.warning(f"Release {version} has no published_at date")
        return None

    # Parse the published date
    try:
        dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
        build_date = dt.date()
    except ValueError as e:
        logger.warning(f"Failed to parse date for {version}: {e}")
        return None

    # Find the openstack-gardener_prod-amd64 tar.xz asset
    pattern = re.compile(r"^openstack-gardener_prod-amd64-.*\.tar\.xz$")

    for asset in release.get("assets", []):
        if pattern.match(asset["name"]):
            url = asset["browser_download_url"]

            # Extract commit hash from filename
            # Format: openstack-gardener_prod-amd64-VERSION-HASH.tar.xz
            filename = asset["name"]
            match = re.search(r"-([a-f0-9]{8})\.tar\.xz$", filename)
            commit_hash = match.group(1) if match else "unknown"

            # Construct mirror URL
            mirror_url = (
                f"https://{MINIO_SERVER}/{MINIO_BUCKET}/"
                f"gardenlinux/{version}/openstack-gardener_prod-amd64-{version}-{commit_hash}.qcow2"
            )

            return {
                "version": version,
                "url": url,
                "mirror_url": mirror_url,
                "build_date": build_date,
                "archive_filename": filename,
            }

    logger.warning(f"No OpenStack gardener_prod-amd64 image found in release {version}")
    return None


def calculate_qcow2_checksum(archive_url: str, archive_filename: str) -> Optional[str]:
    """
    Download tar.xz archive, extract qcow2 file, calculate SHA256 checksum.

    Args:
        archive_url: URL to download the tar.xz archive from
        archive_filename: Name of the archive file

    Returns:
        SHA256 checksum in format "sha256:HEXDIGEST" or None if failed
    """
    logger.info(f"Downloading archive from {archive_url}")

    # Create a unique temporary directory for extraction
    # Extract version from archive_filename for unique temp dir name
    version_match = re.search(r"amd64-(.*?)\.tar\.xz$", archive_filename)
    version_part = version_match.group(1) if version_match else "unknown"
    temp_dir = f"temp_extract_{version_part}"

    try:
        # Download the tar.xz archive
        response = requests.get(archive_url, stream=True, timeout=300)
        response.raise_for_status()

        with open(archive_filename, "wb") as fp:
            for chunk in response.iter_content(chunk_size=8192):
                fp.write(chunk)

        logger.info(f"Downloaded {archive_filename}")

        # Create temporary directory for extraction
        os.makedirs(temp_dir, exist_ok=True)
        logger.info(f"Created temporary extraction directory: {temp_dir}")

        # Extract the archive to temporary directory
        logger.info(f"Extracting {archive_filename} to {temp_dir}")
        patoolib.extract_archive(archive_filename, outdir=temp_dir)

        # Find the extracted qcow2 file
        # Expected format: openstack-gardener_prod-amd64-VERSION-HASH.qcow2
        qcow2_pattern = re.compile(r"^openstack-gardener_prod-amd64-.*\.qcow2$")
        qcow2_file = None

        for file in os.listdir(temp_dir):
            if qcow2_pattern.match(file):
                qcow2_file = os.path.join(temp_dir, file)
                break

        if not qcow2_file:
            logger.error("No qcow2 file found after extraction")
            # Clean up temp directory and archive
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            if os.path.exists(archive_filename):
                os.remove(archive_filename)
            return None

        logger.info(f"Found extracted file: {qcow2_file}")

        # Calculate SHA256 checksum of qcow2 file
        logger.info(f"Calculating SHA256 checksum of {qcow2_file}")
        sha256_hash = hashlib.sha256()

        with open(qcow2_file, "rb") as fp:
            # Read file in chunks to handle large files
            for chunk in iter(lambda: fp.read(8192), b""):
                sha256_hash.update(chunk)

        checksum = f"sha256:{sha256_hash.hexdigest()}"
        logger.info(f"Calculated checksum: {checksum}")

        # Clean up all temporary files and directories
        logger.info("Cleaning up temporary files")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Removed temporary directory: {temp_dir}")
        if os.path.exists(archive_filename):
            os.remove(archive_filename)
            logger.info(f"Removed archive file: {archive_filename}")

        return checksum

    except requests.RequestException as e:
        logger.error(f"Failed to download archive: {e}")
        # Clean up temp directory and archive if they exist
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        if os.path.exists(archive_filename):
            os.remove(archive_filename)
        return None
    except Exception as e:
        logger.error(f"Failed to calculate checksum: {e}")
        # Clean up temp directory and archive if they exist
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        if os.path.exists(archive_filename):
            os.remove(archive_filename)
        return None


def version_exists(versions: list, version_number: str) -> bool:
    """
    Check if a version already exists in the versions list.

    Args:
        versions: List of version dictionaries
        version_number: Version string to check

    Returns:
        True if version exists, False otherwise
    """
    return any(v.get("version") == version_number for v in versions)


@app.command()
def main(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Do not write changes to file"
    ),
    max_releases: int = typer.Option(
        10, "--max-releases", help="Maximum number of releases to check"
    ),
):
    """
    Update gardenlinux.yml with new versions from GitHub releases.
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

    logger.info("Checking for new Garden Linux releases")

    # Fetch latest releases from GitHub
    releases = get_latest_releases(max_releases)
    if not releases:
        logger.error("No releases found")
        return

    logger.info(f"Found {len(releases)} releases")

    # Load current gardenlinux.yml
    logger.info(f"Loading {GARDENLINUX_YML_PATH}")
    ryaml = ruamel.yaml.YAML()
    ryaml.preserve_quotes = True
    ryaml.default_flow_style = False
    ryaml.width = 4096

    try:
        with open(GARDENLINUX_YML_PATH) as fp:
            data = ryaml.load(fp)
    except FileNotFoundError:
        logger.error(f"File {GARDENLINUX_YML_PATH} not found")
        return
    except Exception as e:
        logger.error(f"Failed to load {GARDENLINUX_YML_PATH}: {e}")
        return

    # Find the Garden Linux image entry
    if "images" not in data or not data["images"]:
        logger.error("No images found in YAML file")
        return

    # Assuming there's only one image definition for Garden Linux
    image = data["images"][0]
    current_versions = image.get("versions", [])

    logger.info(f"Current versions in file: {len(current_versions)}")
    if current_versions:
        latest = current_versions[0].get("version", "unknown")
        logger.info(f"Latest version in file: {latest}")

    # Process only the latest release and append to the end if new
    latest_release = releases[0]
    image_info = extract_openstack_image(latest_release)

    if not image_info:
        logger.info("No OpenStack image found in latest release")
        return

    version_number = image_info["version"]

    if version_exists(current_versions, version_number):
        logger.info(f"Latest version {version_number} already exists")
        return

    logger.info(f"Found new version: {version_number}")
    logger.info(f"  URL: {image_info['url']}")
    logger.info(f"  Build date: {image_info['build_date']}")

    # Calculate the checksum by downloading and extracting the qcow2 file
    logger.info("Calculating checksum of qcow2 file inside archive")
    checksum = calculate_qcow2_checksum(
        image_info["url"], image_info["archive_filename"]
    )

    if not checksum:
        logger.error("Failed to calculate checksum, aborting")
        return

    logger.info(f"  Checksum: {checksum}")

    # Add checksum to image_info and remove archive_filename
    image_info["checksum"] = checksum
    del image_info["archive_filename"]

    logger.info("Adding new version to the end of versions list")

    # Append the new version to the end of the list
    current_versions.append(image_info)

    if dry_run:
        logger.info("Dry-run mode: not writing changes to file")
        logger.info(f"Would add version {version_number}")
    else:
        # Write updated YAML
        logger.info(f"Writing updated file to {GARDENLINUX_YML_PATH}")
        try:
            with open(GARDENLINUX_YML_PATH, "w") as fp:
                ryaml.explicit_start = True
                ryaml.default_flow_style = False
                ryaml.width = 4096
                ryaml.indent(sequence=4, offset=2)
                ryaml.dump(data, fp)
            logger.info("File updated successfully")
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            return


if __name__ == "__main__":
    app()
