# SPDX-License-Identifier: Apache-2.0

import time
import openstack
import requests
import yaml
import os
import re
import sys
import typer
import typing
from typing import Dict, Set
import yamale
import urllib.parse
import pkgutil

from datetime import datetime, date
from decimal import Decimal, ROUND_UP
from loguru import logger
from munch import Munch
from natsort import natsorted
from yamale import YamaleError
from openstack.image.v2.image import Image


class ImageManager:
    def __init__(self) -> None:
        self.exit_with_error = False

    def create_cli_args(
        self,
        debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Do not perform any changes"
        ),
        check_age: bool = typer.Option(
            False, "--check-age", help="Check openstack image age against definition"
        ),
        max_age: int = typer.Option(
            90, "--max-age", help="The age of an image in days to be considered too old"
        ),
        latest: bool = typer.Option(
            False,
            "--latest",
            help="Only import the latest version for images of type multi",
        ),
        keep: bool = typer.Option(
            False,
            "--keep",
            help="Keep versions of images where the version is not longer defined",
        ),
        cloud: str = typer.Option("openstack", help="Cloud name in clouds.yaml"),
        images: str = typer.Option(
            "etc/images/",
            help="Path to the directory containing all image files or path to "
            "a single image file",
        ),
        tag: str = typer.Option(
            "managed_by_osism", help="Name of the tag used to identify managed images"
        ),
        filter: str = typer.Option(
            None, help="Filter images with a regex on their name"
        ),
        deactivate: bool = typer.Option(
            False, "--deactivate", help="Deactivate images that should be deleted"
        ),
        hide: bool = typer.Option(
            False, "--hide", help="Hide images that should be deleted"
        ),
        force: bool = typer.Option(
            False, "--force", help="Force upload of disabled images"
        ),
        delete: bool = typer.Option(False, "--delete", help="Delete outdated images"),
        yes_i_really_know_what_i_do: bool = typer.Option(
            False, "--yes-i-really-know-what-i-do", help="Really delete images"
        ),
        use_os_hidden: bool = typer.Option(
            False, "--use-os-hidden", help="Use the os_hidden property"
        ),
        share_image: str = typer.Option(
            None, "--share-image", help="Share - Image to share"
        ),
        share_action: str = typer.Option(
            "add", "--share-action", help="Share - Action: 'del' or 'add'"
        ),
        share_domain: str = typer.Option(
            "default", "--share-domain", help="Share - Project domain"
        ),
        share_target: str = typer.Option(
            None, "--share-target", help="Share - Target project domain"
        ),
        share_type: str = typer.Option(
            "project", "--share-type", help="Share - Type: 'project' or 'domain'"
        ),
        check: bool = typer.Option(
            True,
            "--check/--no-check",
            help="Check the local image definitions against the SCS Image Metadata Standard (and process the images)",
        ),
        check_only: bool = typer.Option(
            False,
            "--check-only",
            help="Quit after checking the image definitions against the SCS Image Metadata Standard",
        ),
    ):
        self.CONF = Munch.fromDict(locals())
        self.CONF.pop("self")  # remove the self object from CONF

        if self.CONF.debug:
            level = "DEBUG"
            log_fmt = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
                "<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
            )
        else:
            level = "INFO"
            log_fmt = (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
                "<level>{message}</level>"
            )

        logger.remove()
        logger.add(sys.stderr, format=log_fmt, level=level, colorize=True)

        if __name__ == "__main__" or __name__ == "openstack_image_manager.main":
            self.main()

    def read_image_files(self, return_all_images=False) -> list:
        """Read all YAML files in self.CONF.images"""
        image_files = []

        if os.path.isdir(self.CONF.images):
            for file in os.listdir(self.CONF.images):
                if file.endswith(tuple([".yml", "yaml"])):
                    image_files.append(file)
        else:
            image_files = [self.CONF.images]

        all_images = []
        for file in image_files:
            if os.path.isdir(self.CONF.images):
                file = os.path.join(self.CONF.images, file)
            with open(file) as fp:
                try:
                    data = yaml.load(fp, Loader=yaml.SafeLoader)
                    images = data.get("images")
                    for image in images:
                        if return_all_images:
                            all_images.append(image)

                        elif self.CONF.filter:
                            if re.search(self.CONF.filter, image["name"]):
                                if "enable" in image and (
                                    (image["enable"])
                                    or (not image["enable"] and self.CONF.force)
                                ):
                                    all_images.append(image)
                                elif "enable" not in image:
                                    all_images.append(image)
                        else:
                            if "enable" in image and (
                                (image["enable"])
                                or (not image["enable"] and self.CONF.force)
                            ):
                                all_images.append(image)
                            elif "enable" not in image:
                                all_images.append(image)
                except yaml.YAMLError as exc:
                    logger.error(exc)
        return all_images

    def get_checksum(self, url: str, checksums_url: str) -> str:
        """
        Get the checksum of an upstream image by parsing its corresponding checksums file

        Params:
            url: the download URL of the image
            checksums_url: the URL of the corresponding checksums file

        Returns:
            the matching checksum, if it is available or else an empty string
        """
        filename = url.split("/")[-1]
        checksums_file = requests.get(checksums_url).text
        for line in checksums_file.splitlines():
            if filename in line:
                split = line.split(" ")
                for elem in split:
                    if (
                        len(elem) == 128
                        or len(elem) == 64
                        or len(elem) == 40
                        or len(elem) == 32
                    ) and "." not in elem:
                        return elem
        return ""

    def create_connection(self) -> None:
        if "OS_AUTH_URL" in os.environ:
            self.conn = openstack.connect()
        else:
            self.conn = openstack.connect(cloud=self.CONF.cloud)

    def main(self) -> None:
        """
        Read all files in etc/images/ and process each image
        Rename outdated images when not dry-running
        """
        logger.debug(f"cloud = {self.CONF.cloud}")
        logger.debug(f"dry-run = {self.CONF.dry_run}")
        logger.debug(f"images = {self.CONF.images}")
        logger.debug(f"tag = {self.CONF.tag}")
        logger.debug(
            f"yes-i-really-know-what-i-do = {self.CONF.yes_i_really_know_what_i_do}"
        )

        # check local image definitions with yamale
        if self.CONF.check or self.CONF.check_only:
            self.validate_yaml_schema()

        if self.CONF.check_only:
            return

        # share image (previously share.py)
        if self.CONF.share_image:
            self.create_connection()
            image = self.conn.get_image(self.CONF.share_image)

            if self.CONF.share_type == "project":
                domain = self.conn.get_domain(name_or_id=self.CONF.share_domain)
                project = self.conn.get_project(
                    self.CONF.share_target, domain_id=domain.id
                )

                if self.CONF.share_action == "add":
                    self.share_image_with_project(image, project)
                elif self.CONF.share_action == "del":
                    self.unshare_image_with_project(image, project)

            elif self.CONF.share_type == "domain":
                domain = self.conn.get_domain(name_or_id=self.CONF.share_target)
                projects = self.conn.list_projects(domain_id=domain.id)
                for project in projects:
                    if self.CONF.share_action == "add":
                        self.share_image_with_project(image, project)
                    elif self.CONF.share_action == "del":
                        self.unshare_image_with_project(image, project)

        # manage images
        else:
            self.create_connection()
            images = self.read_image_files()
            managed_images = self.process_images(images)

            # ignore all non-specified images when using --filter
            if self.CONF.filter:
                cloud_images = self.get_images()
                for image in cloud_images:
                    if not re.search(self.CONF.filter, image):
                        managed_images.add(image)

            if self.CONF.check_age:
                self.check_image_age()

            self.manage_outdated_images(managed_images)

        if self.exit_with_error:
            sys.exit(
                "\nERROR: One or more errors occurred during the execution of the program, "
                "please check the output."
            )

    def process_images(self, images) -> set:
        """Process each image from images.yaml"""

        REQUIRED_KEYS = [
            "format",
            "name",
            "login",
            "status",
            "versions",
            "visibility",
        ]
        managed_images: Set[str] = set()

        for image in images:
            for required_key in REQUIRED_KEYS:
                if required_key not in image:
                    logger.error(
                        f"'{image['name']}' lacks the necessary key {required_key}"
                    )
                    self.exit_with_error = True
                    continue

            logger.debug(f"Processing '{image['name']}'")

            try:
                versions = dict()
                for version in image["versions"]:
                    versions[str(version["version"])] = {"url": version["url"]}

                    if "mirror_url" in version:
                        versions[version["version"]]["mirror_url"] = version[
                            "mirror_url"
                        ]

                    if "visibility" in version:
                        versions[version["version"]]["visibility"] = version[
                            "visibility"
                        ]

                    if "os_version" in version:
                        versions[version["version"]]["os_version"] = version[
                            "os_version"
                        ]

                    if "hidden" in version:
                        versions[version["version"]]["hidden"] = version["hidden"]

                    if version["version"] == "latest":  #
                        if "checksums_url" in version:
                            versions[version["version"]]["checksums_url"] = version[
                                "checksums_url"
                            ]
                        else:
                            raise ValueError(
                                'Key "checksums_url" is required when using version "latest"'
                            )

                    if "meta" in version:
                        versions[version["version"]]["meta"] = version["meta"]
                    else:
                        versions[version["version"]]["meta"] = {}

                    if "url" in version:
                        url = version["url"]
                        # strip any directory path for file: urls in order to
                        # avoid exposing local filesystem details to other users
                        if url.startswith("file:") and "/" in url:
                            urlfile = url.rsplit("/", 1)[1]
                            url = f"file:{urlfile}"
                        versions[version["version"]]["meta"]["image_source"] = url

                    if "build_date" in version:
                        versions[version["version"]]["meta"]["image_build_date"] = (
                            date.isoformat(version["build_date"])
                        )

                    if "id" in version:
                        versions[version["version"]]["id"] = version["id"]
            except ValueError as e:
                logger.error(str(e))
                continue
            except Exception as e:
                logger.error(f"An unexpected error occurred: {e}")
                continue

            sorted_versions = natsorted(versions.keys())
            image["tags"].append(self.CONF.tag)

            if "os_distro" in image["meta"]:
                image["tags"].append(f"os:{image['meta']['os_distro']}")

            if "image_description" not in image["meta"]:
                image["meta"]["image_description"] = image["name"]

            if "image_name" not in image["meta"]:
                image["meta"]["image_name"] = image["name"]

            existing_images, imported_image, previous_image = self.process_image(
                image, versions, sorted_versions, image["meta"].copy()
            )
            managed_images = managed_images.union(existing_images)

            if imported_image and image["multi"]:
                self.rename_images(
                    image, sorted_versions, imported_image, previous_image
                )

        return managed_images

    def import_image(
        self, image: dict, name: str, url: str, versions: dict, version: str
    ) -> typing.Union[Image, None]:
        """
        Create a new image in Glance and upload it using the web-download method

        Params:
            image: image dict from images.yml
            name: name of the image to import
            url: download URL of the image
            versions: versions dict generated by main()
            version: currently processed version
        """
        logger.info(f"Importing image {name}")
        logger.info(f"Importing from URL {url}")

        properties = {
            "container_format": "bare",
            "disk_format": image["format"],
            "min_disk": image.get("min_disk", 0),
            "min_ram": image.get("min_ram", 0),
            "name": name,
            "tags": [self.CONF.tag],
            "visibility": "private",
        }
        if "id" in versions[version]:
            properties["id"] = versions[version]["id"]

        new_image = self.conn.image.create_image(**properties)
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme == "file":
            local_file = open(parsed_url.path, "rb")
            with local_file:
                try:
                    logger.info(
                        f"Uploading local file '{parsed_url.path}' as image {name}"
                    )
                    new_image.data = local_file
                    new_image.upload(self.conn.image)
                except Exception as e:
                    self.conn.image.delete_image(new_image)
                    logger.error(f"Failed to upload local file for image {name}\n{e}")
                    self.exit_with_error = True
                    return None
        else:
            self.conn.image.import_image(new_image, method="web-download", uri=url)

        return self.wait_for_image(new_image)

    def get_images(self) -> dict:
        """
        Load all images from OpenStack and filter by the tag set by the --tag CLI option

        Returns:
            a dict containing all matching images as openstack.image.v2.image.Image objects
        """
        result = {}

        for image in self.conn.image.images():
            if self.CONF.tag in image.tags and (
                image.visibility == "public"
                or image.owner == self.conn.current_project_id
            ):
                result[image.name] = image
                logger.debug(f"Managed image '{image.name}' (tags = {image.tags})")
            else:
                logger.debug(f"Unmanaged image '{image.name}' (tags = {image.tags})")

        if self.CONF.use_os_hidden:
            for image in self.conn.image.images(**{"os_hidden": True}):
                if self.CONF.tag in image.tags and (
                    image.visibility == "public"
                    or image.owner == self.conn.current_project_id
                ):
                    result[image.name] = image
                    logger.debug(
                        f"Managed hidden image '{image.name}' (tags = {image.tags})"
                    )
                else:
                    logger.debug(
                        f"Unmanaged hidden image '{image.name}' (tags = {image.tags})"
                    )
        return result

    def wait_for_image(self, image: Image) -> typing.Union[Image, None]:
        """
        Wait for an imported image to reach "active" state

        Returns:
            the openstack.image.v2.image.Image object representing the imported image
            if the image has reached "active" state or None if the image seems stuck
            in "queued" state
        """
        retry_attempts_for_queued_state = 4
        while True:
            try:
                imported_image = self.conn.image.get_image(image)
                # An image's state in Glance transitions as follows:
                #   queued > importing/saving > active
                # If an import fails (e.g. web-download task API disabled),
                # it silently falls back to "queued" state asynchronously in
                # the background. We need to catch such cases where an image is
                # indefinitely stuck in "queued" state.
                if imported_image.status == "queued":
                    if retry_attempts_for_queued_state < 0:
                        logger.error(f"Image {image.name} seems stuck in queued state")
                        self.exit_with_error = True
                        return None
                    else:
                        retry_attempts_for_queued_state -= 1
                        logger.info("Waiting for image to leave queued state...")
                        time.sleep(2.0)
                elif imported_image.status != "active":
                    logger.info("Waiting for import to complete...")
                    time.sleep(10.0)
                else:
                    return imported_image
            except Exception as e:
                logger.error(f"Exception while importing image {image.name}\n{e}")
                self.exit_with_error = True

    def process_image(
        self, image: dict, versions: dict, sorted_versions: list, meta: dict
    ) -> tuple:
        """
        Process one image from etc/images/
        Check if the image already exists in Glance and import it if not

        Params:
            image: image dict from images.yml
            versions: versions dict generated by main()
            sorted_versions: list with all sorted image versions
            meta: metadata of the image, does not include version-specific metadata

        Returns:
            Tuple with (existing_images, imported_image, previous_image)
        """
        cloud_images = self.get_images()

        existing_images: Set[str] = set()
        imported_image = None
        previous_image = None
        upstream_checksum = ""

        separator = image.get("separator", " ")
        image_name = image["name"]

        for version in sorted_versions:
            if image["multi"]:
                name = f"{image_name}{separator}({version})"
            else:
                name = f"{image_name}{separator}{version}"

            logger.info(f"Processing image '{name}'")
            logger.debug(f"Checking existence of '{name}'")
            existence = name in cloud_images

            if existence and cloud_images[name].status != "active":
                self.wait_for_image(cloud_images[name])

            if (
                image["multi"]
                and self.CONF.latest
                and version == sorted_versions[-1]
                and not existence
            ):
                existence = image["name"] in cloud_images
                try:
                    if existence:
                        existence = (
                            cloud_images[image["name"]]["properties"][
                                "internal_version"
                            ]
                            == version
                        )
                except KeyError:
                    logger.error(
                        f"Image {image['name']} is missing property 'internal_version'"
                    )

            elif (
                image["multi"]
                and len(sorted_versions) > 1
                and version == sorted_versions[-1]
                and not existence
            ):
                previous = f"{image['name']}{separator}({sorted_versions[-2]})"
                existence = previous in cloud_images and image["name"] in cloud_images

            elif (
                image["multi"]
                and len(sorted_versions) > 1
                and version == sorted_versions[-2]
                and not existence
            ):
                existence = image["name"] in cloud_images

            elif image["multi"] and len(sorted_versions) == 1:
                existence = image["name"] in cloud_images

            if version == "latest":
                checksums_url = versions[version]["checksums_url"]
                upstream_checksum = self.get_checksum(
                    versions[version]["url"], checksums_url
                )
                if not upstream_checksum:
                    logger.error(
                        f"Could not find checksum for image '{image['name']}', check the checksums_url"
                    )
                    return existing_images, imported_image, previous_image

                try:
                    image_checksum = (
                        cloud_images[image["name"]]["properties"]["upstream_checksum"]
                        if image["name"] in cloud_images
                        else ""
                    )
                    if image_checksum == upstream_checksum:
                        logger.info(f"No new version for '{image['name']}'")
                        existing_images.add(image["name"])
                        return existing_images, imported_image, previous_image
                    else:
                        logger.info(f"New version for '{image['name']}'")
                        existence = False
                except KeyError:
                    # when switching from a release pointer to a latest pointer, the image has no checksum property
                    existence = False

            if not existence and not (
                self.CONF.latest
                and len(sorted_versions) > 1
                and version != sorted_versions[-1]
            ):
                # use `mirror_url` for download if given, else fall back to `url`
                # in any case, `url` will be used to set `image_source` property
                url = versions[version].get("mirror_url", versions[version]["url"])
                parsed_url = urllib.parse.urlparse(url)
                if parsed_url.scheme == "file":
                    file_path = parsed_url.path
                    if not (os.path.exists(file_path) and os.path.isfile(file_path)):
                        logger.error(
                            f"Skipping '{name}' due to file '{file_path}' not found locally"
                        )
                        self.exit_with_error = True
                        return existing_images, imported_image, previous_image
                else:
                    r = requests.head(url)

                    if r.status_code in [200, 302]:
                        logger.info(f"Tested URL {url}: {r.status_code}")
                    else:
                        logger.error(f"Tested URL {url}: {r.status_code}")
                        logger.error(
                            f"Skipping '{name}' due to HTTP status code {r.status_code}"
                        )
                        self.exit_with_error = True
                        return existing_images, imported_image, previous_image

                if image["multi"] and image["name"] in cloud_images:
                    previous_image = cloud_images[image["name"]]

                if not self.CONF.dry_run:
                    import_result = self.import_image(
                        image, name, url, versions, version
                    )
                    if import_result:
                        logger.info(
                            f"Import of '{name}' successfully completed, reloading images"
                        )
                        cloud_images = self.get_images()
                        imported_image = cloud_images.get(name, None)
                else:
                    logger.info(
                        f"Skipping required import of image '{name}', running in dry-run mode"
                    )

            elif self.CONF.latest and version != sorted_versions[-1]:
                logger.info(
                    f"Skipping image '{name}' (only importing the latest version from type multi)"
                )

            if image["multi"]:
                existing_images.add(image["name"])
            else:
                existing_images.add(name)

            if imported_image:
                self.set_properties(
                    image.copy(), name, versions, version, upstream_checksum, meta
                )
        return existing_images, imported_image, previous_image

    def set_properties(
        self,
        image: dict,
        name: str,
        versions: dict,
        version: str,
        upstream_checksum: str,
        meta: dict,
    ):
        """
        Set image properties and tags based on the configuration from images.yml

        Params:
            image: image dict from images.yml
            name: name of the image including the version string
            versions: versions dict generated by main()
            version: currently processed version
            meta: metadata of the image, does not include version-specific metadata
        """
        cloud_images = self.get_images()
        image["meta"] = meta.copy()

        if name in cloud_images:
            logger.info(f"Checking parameters of '{name}'")

            cloud_image = cloud_images[name]
            real_image_size = int(
                Decimal(cloud_image.size / 2**30).quantize(
                    Decimal("1."), rounding=ROUND_UP
                )
            )

            if "min_disk" in image and image["min_disk"] != cloud_image.min_disk:
                logger.info(
                    f"Setting min_disk: {image['min_disk']} != {cloud_image.min_disk}"
                )
                self.conn.image.update_image(
                    cloud_image.id, **{"min_disk": int(image["min_disk"])}
                )

            if (
                "min_disk" in image and real_image_size > image["min_disk"]
            ) or "min_disk" not in image:
                logger.info(f"Setting min_disk = {real_image_size}")
                self.conn.image.update_image(
                    cloud_image.id, **{"min_disk": real_image_size}
                )

            if "min_ram" in image and image["min_ram"] != cloud_image.min_ram:
                logger.info(
                    f"Setting min_ram: {image['min_ram']} != {cloud_image.min_ram}"
                )
                self.conn.image.update_image(
                    cloud_image.id, **{"min_ram": int(image["min_ram"])}
                )

            if self.CONF.use_os_hidden:
                if "hidden" in versions[version]:
                    logger.info(f"Setting os_hidden = {versions[version]['hidden']}")
                    self.conn.image.update_image(
                        cloud_image.id, **{"os_hidden": versions[version]["hidden"]}
                    )

                elif version != natsorted(versions.keys())[-1:]:
                    logger.info("Setting os_hidden = True")
                    self.conn.image.update_image(cloud_image.id, **{"os_hidden": True})

            if version == "latest":
                try:
                    url = versions[version]["url"]
                    modify_date = requests.head(url, allow_redirects=True).headers[
                        "Last-Modified"
                    ]

                    date_format = "%a, %d %b %Y %H:%M:%S %Z"
                    modify_date = str(
                        datetime.strptime(modify_date, date_format).date()
                    )
                    modify_date = modify_date.replace("-", "")

                    logger.info(f"Setting internal_version = {modify_date}")
                    image["meta"]["internal_version"] = modify_date
                except Exception:
                    logger.error(
                        f"Error when retrieving the modification date of image '{image['name']}'"
                    )
                    logger.info(f"Setting internal_version = {version}")
                    image["meta"]["internal_version"] = version
            else:
                logger.info(f"Setting internal_version = {version}")
                image["meta"]["internal_version"] = version

            logger.info(f"Setting image_original_user = {image['login']}")
            image["meta"]["image_original_user"] = image["login"]

            if version == "latest" and upstream_checksum:
                image["meta"]["upstream_checksum"] = upstream_checksum

            if image["multi"] and "os_version" in versions[version]:
                image["meta"]["os_version"] = versions[version]["os_version"]
            elif not image["multi"]:
                image["meta"]["os_version"] = version

            for tag in image["tags"]:
                if tag not in cloud_image.tags:
                    logger.info(f"Adding tag {tag}")
                    self.conn.image.add_tag(cloud_image.id, tag)

            for tag in cloud_image.tags:
                if tag not in image["tags"]:
                    logger.info(f"Deleting tag {tag}")
                    self.conn.image.remove_tag(cloud_image.id, tag)

            if "meta" in versions[version]:
                for key in versions[version]["meta"].keys():
                    image["meta"][key] = versions[version]["meta"][key]

            properties = cloud_image.properties
            for property in properties:
                if property in image["meta"]:
                    if image["meta"][property] != properties[property]:
                        logger.info(
                            f"Setting property {property}: {properties[property]} != {image['meta'][property]}"
                        )
                        self.conn.image.update_image(
                            cloud_image.id, **{property: str(image["meta"][property])}
                        )

                elif property not in [
                    "self",
                    "schema",
                    "stores",
                ] or not property.startswith("os_"):
                    # FIXME: handle deletion of properties
                    logger.debug(f"Deleting property {property}")

            for property in image["meta"]:
                if property not in properties:
                    logger.info(
                        f"Setting property {property}: {image['meta'][property]}"
                    )
                    self.conn.image.update_image(
                        cloud_image.id, **{property: str(image["meta"][property])}
                    )

            logger.info(f"Checking status of '{name}'")
            if (
                cloud_image.status != image["status"]
                and image["status"] == "deactivated"
            ):
                logger.info(f"Deactivating image '{name}'")
                self.conn.image.deactivate_image(cloud_image.id)

            elif cloud_image.status != image["status"] and image["status"] == "active":
                logger.info(f"Reactivating image '{name}'")
                self.conn.image.reactivate_image(cloud_image.id)

            logger.info(f"Checking visibility of '{name}'")
            if "visibility" in versions[version]:
                visibility = versions[version]["visibility"]
            else:
                visibility = image["visibility"]

            if cloud_image.visibility != visibility:
                logger.info(f"Setting visibility of '{name}' to '{visibility}'")
                self.conn.image.update_image(cloud_image.id, visibility=visibility)

    def rename_images(
        self,
        image: dict,
        sorted_versions: list,
        imported_image: Image,
        previous_image: Image,
    ) -> None:
        """
        Rename outdated images in Glance (only applies to images of type multi)

        Params:
            image: image dict from images.yml
            sorted_versions: list with all sorted image versions
            imported_image: the newly imported image
            previous_image: the previous latest image
        """
        name = image["name"]
        separator = image.get("separator", " ")
        cloud_images = self.get_images()

        if len(sorted_versions) > 1:
            latest = f"{name}{separator}({sorted_versions[-1]})"
            previous_latest = f"{name}{separator}({sorted_versions[-2]})"

            if name in cloud_images and previous_latest not in cloud_images:
                logger.info(f"Renaming {name} to {previous_latest}")
                self.conn.image.update_image(
                    cloud_images[name].id, name=previous_latest
                )

            if latest in cloud_images:
                logger.info(f"Renaming {latest} to {name}")
                self.conn.image.update_image(cloud_images[latest].id, name=name)

        elif len(sorted_versions) == 1 and name in cloud_images:
            if previous_image["properties"]["internal_version"] == "latest":
                # if the last modification date cannot be found, use the creation date of the image instead
                create_date = str(
                    datetime.strptime(
                        previous_image.created_at, "%Y-%m-%dT%H:%M:%SZ"
                    ).date()
                )
                create_date = create_date.replace("-", "")

                previous_latest = f"{name}{separator}({create_date})"

                logger.info(
                    f"Setting internal_version: {create_date} for {previous_latest}"
                )
                self.conn.image.update_image(
                    previous_image.id, **{"internal_version": create_date}
                )
            else:
                previous_latest = f"{name}{separator}({previous_image['properties']['internal_version']})"

            logger.info(f"Renaming old latest '{name}' to '{previous_latest}'")
            self.conn.image.update_image(previous_image.id, name=previous_latest)

            logger.info(f"Renaming imported image '{imported_image.name}' to '{name}'")
            self.conn.image.update_image(imported_image.id, name=name)

        elif len(sorted_versions) == 1:
            latest = f"{name}{separator}({sorted_versions[-1]})"

            if latest in cloud_images:
                logger.info(f"Renaming {latest} to {name}")
                self.conn.image.update_image(cloud_images[latest].id, name=name)

    def check_image_age(self) -> set:
        """
        Check the age of the images in OpenStack and compare with the
        image definitions. Return a set of image names that are too old.

        Returns:
            set: A set of image names that are older than the max age.
        """
        logger.info(f"Checking for openstack images of age {str(self.CONF.max_age)}")

        images = {}
        for d in self.read_image_files(return_all_images=True):
            images[d["name"]] = d

        cloud_images = self.get_images()

        too_old_images = set()

        for cloud_image_name, cloud_image in cloud_images.items():
            image_name = cloud_image.properties["image_description"]

            if image_name not in images:
                logger.warning(
                    f"No image definition found for '{image_name}', image will be ignored"
                )
                continue

            image_definition = images[image_name]

            build_date_backend = date.fromisoformat(
                cloud_image.properties["image_build_date"]
            )

            if image_definition["multi"]:
                build_date_definition_candidates = [
                    x["build_date"] for x in image_definition["versions"]
                ]
            else:
                build_date_definition_candidates = []
                for v in image_definition["versions"]:
                    if v["version"] != cloud_image.os_version:
                        continue
                    build_date_definition_candidates.append(v["build_date"])

            if len(build_date_definition_candidates) == 0:
                logger.warning(
                    f"No compatible version definition found for '{cloud_image_name}', image will be ignored"
                )
                continue

            build_date_definition_candidates.sort(reverse=True)
            build_date_definition = build_date_definition_candidates[0]

            logger.info(
                f"Image '{cloud_image_name}' was created on {str(build_date_backend)}"
            )

            age_difference_days = (build_date_definition - build_date_backend).days
            if age_difference_days > self.CONF.max_age:
                logger.warning(
                    f"Image '{cloud_image_name}' is {age_difference_days} days "
                    f"older than the newest image in the definition"
                )
                too_old_images.add(cloud_image_name)

        return too_old_images

    def manage_outdated_images(self, managed_images: set) -> list:
        """
        Delete, hide or deactivate outdated images

        Params:
            managed_images: set of managed images
        Raises:
            Exception: when the image is still in use and cannot be deleted
            Exception: when the image cannot be deactivated or its visibility cannot be changed
        Returns:
            List with all images that are unmanaged and get affected by this method
        """

        images = {}
        for d in self.read_image_files(return_all_images=True):
            images[d["name"]] = d
        cloud_images = self.get_images()

        # NOTE: ensure to not handle images that should be not handled
        if self.CONF.filter:
            unmanaged_images = natsorted(
                [
                    x
                    for x in cloud_images
                    if x not in managed_images and re.search(self.CONF.filter, x)
                ],
                reverse=True,
            )
        else:
            unmanaged_images = natsorted(
                [x for x in cloud_images if x not in managed_images], reverse=True
            )

        counter: Dict[str, int] = {}

        for image in unmanaged_images:
            logger.info(f"Processing image '{image}' (removal candidate)")

            cloud_image = cloud_images[image]
            image_name = cloud_image.properties["image_description"]

            if image_name not in images:
                logger.warning(
                    f"No image definition found for '{image}', image will be ignored"
                )
                continue

            # Always skip the last imported image
            if image_name == image:
                continue

            image_definition = images[image_name]
            counter[image_name] = counter.get(image_name, 0) + 1

            uuid_validity = cloud_image.properties["uuid_validity"]
            if "last" in uuid_validity:
                last = int(uuid_validity[5:]) - 1
            else:
                last = 0

            if self.CONF.keep and not image_definition["multi"]:
                logger.info(
                    f"Image '{image}' will not be deleted, undefined versions of defined images are kept"
                )

            elif uuid_validity == "none":
                logger.info(
                    f"Image '{image}' will not be deleted, UUID validity is 'none'"
                )
            elif counter[image_name] > last:
                if (
                    self.CONF.delete
                    and self.CONF.yes_i_really_know_what_i_do
                    and not self.CONF.dry_run
                ):
                    try:
                        logger.info(f"Deactivating image '{image}'")
                        self.conn.image.deactivate_image(cloud_image.id)

                        logger.info(f"Setting visibility of '{image}' to 'community'")
                        self.conn.image.update_image(
                            cloud_image.id, visibility="community"
                        )

                        if (
                            "keep" not in image_definition
                            or not image_definition["keep"]
                        ):
                            logger.info(f"Deleting {image}")
                            self.conn.image.delete_image(cloud_image.id)
                        else:
                            logger.info(
                                f"Image '{image}' will not be deleted, because 'keep' flag is True"
                            )
                    except Exception as e:
                        logger.info(
                            f"{image} is still in use and cannot be deleted\n {e}"
                        )

                else:
                    logger.warning(
                        f"Image {image} should be deleted, but deletion is disabled"
                    )
                    try:
                        if self.CONF.deactivate and not self.CONF.dry_run:
                            logger.info(f"Deactivating image '{image}'")
                            self.conn.image.deactivate_image(cloud_image.id)

                        if (
                            self.CONF.hide
                            and not self.CONF.dry_run
                            and cloud_image.visibility != "community"
                        ):
                            logger.info(
                                f"Setting visibility of '{image}' to 'community'"
                            )
                            self.conn.image.update_image(
                                cloud_image.id, visibility="community"
                            )
                    except Exception as e:
                        logger.error(f"An Exception occurred: \n{e}")
                        self.exit_with_error = True
            elif counter[image_name] <= last:
                logger.info(
                    f"Image '{image}' will not be deleted, {counter[image_name]} <= {last}"
                )
                if (
                    self.CONF.hide
                    and not self.CONF.dry_run
                    and cloud_image.visibility != "community"
                ):
                    logger.info(f"Setting visibility of '{image}' to 'community'")
                    self.conn.image.update_image(cloud_image.id, visibility="community")
            elif (
                counter[image_name] < last and self.CONF.hide and not self.CONF.dry_run
            ):
                logger.info(f"Setting visibility of '{image}' to 'community'")
                self.conn.image.update_image(cloud_image.id, visibility="community")
        return unmanaged_images

    def validate_yaml_schema(self):
        """Validate all image.yaml files against the SCS Metadata spec"""
        try:
            # We are a pip package
            schema_data = pkgutil.get_data(__name__, "etc/schema.yaml").decode("utf-8")
            schema = yamale.make_schema(content=schema_data)
        except Exception:
            # We are a cloned repo
            schema = yamale.make_schema("etc/schema.yaml")

        try:
            validation_error_log = []

            if os.path.isdir(self.CONF.images):
                files = [
                    os.path.join(self.CONF.images, file)
                    for file in os.listdir(self.CONF.images)
                ]
            else:
                files = [self.CONF.images]

            for file in files:
                try:
                    data = yamale.make_data(file)
                    yamale.validate(schema, data)
                except YamaleError as e:
                    for result in e.results:
                        logger.error(
                            f"Error validating data '{result.data}' with '{result.schema}'"
                        )
                        for error in result.errors:
                            logger.error(f"\t{error}")
                            validation_error_log.append((file, error))
                else:
                    logger.debug(f"Image file {file} is valid")
        except FileNotFoundError:
            logger.error(f"Invalid path '{self.CONF.images}'")

        if len(validation_error_log) > 0:
            sys.exit(
                f"Image definition validation failed with these error(s): {validation_error_log}"
            )

    def share_image_with_project(self, image, project):
        member = self.conn.image.find_member(project.id, image.id)

        if not member:
            logger.info(f"add - {image.name} - {project.name} ({project.domain_id})")
            if not self.CONF.dry_run:
                member = self.conn.image.add_member(image.id, member_id=project.id)

        if not self.CONF.dry_run and member.status != "accepted":
            logger.info(f"accept - {image.name} - {project.name} ({project.domain_id})")
            self.conn.image.update_member(member, image.id, status="accepted")

    def unshare_image_with_project(self, image, project):
        member = self.conn.image.find_member(project.id, image.id)

        if member:
            logger.info(f"del - {image.name} - {project.name} ({project.domain_id})")
            if not self.CONF.dry_run:
                self.conn.image.remove_member(member, image.id)


def main():
    image_manager = ImageManager()
    typer.run(image_manager.create_cli_args)


if __name__ == "__main__":
    main()
