#!/usr/bin/env python3
import sys
from crawler.web.generic import url_exists
from crawler.web.directory import web_get_checksum
from crawler.core.database import database_connect, database_disconnect, write_catalog_entry

import requests
from bs4 import BeautifulSoup
from pprint import pprint

from crawler.core.config import config_read

import re


def get_all_versions_with_paths_from_directory(release):
    version_paths = {}

    # get release directory content
    if "debian" in release['imagename']:
        requestURL = release['baseURL']
        version_regex = re.compile(r'(\d{8}-\d*)')
        path_regex = version_regex
    elif "ubuntu" in release['imagename']:
        requestURL = release['baseURL']
        version_regex = re.compile(r'release-(\d{8})\.*\d*')
        path_regex = re.compile(r'(release-\d{8}\.*\d*)')
    else:
        # not yet supported
        return version_paths
        # requestURL = release['baseURL'] + release['releasepath']
        # workaround for Alma
        # version_regex = re.compile(r'AlmaLinux-9-GenericCloud-9.0-(\d{8})')
        # path_regex = re.compile(r'AlmaLinux-9-GenericCloud-9.0-(\d{8})')

    request = requests.get(requestURL, allow_redirects=True)
    soup = BeautifulSoup(request.text, "html.parser")

    last_version = ""
    for link in soup.find_all("a"):
        data = link.get('href')
        # print(data)
        match = version_regex.search(data)
        if match is not None:
            # just use first occurance of matching pattern
            # Debian has two links for one version
            if match.group(1) != last_version:
                version = match.group(1)
                version_paths[version] = {}
                path_match = path_regex.search(data)
                version_paths[version]['path'] = path_match.group(1)
                last_version = version

    return version_paths


# only Debian and Ubuntu?
def get_version_path(release, version):

    pprint(version)
    pprint(release)
    # get release directory content
    if "debian" in release['imagename']:
        requestURL = release['baseURL']
        version_regex = re.compile(r'\d8-\d*')
    elif "ubuntu" in release['imagename']:
        requestURL = release['baseURL']
        version_regex = re.compile(r'release-\d{8}\.*\d*')
    # not yet supported
    # else:
    #     requestURL = release['baseURL'] + release['releasepath']
    #     version_regex = re.compile(r'AlmaLinux-9-GenericCloud-9.0-\d{8}')

    request = requests.get(requestURL, allow_redirects=True)
    soup = BeautifulSoup(request.text, "html.parser")

    for link in soup.find_all("a"):
        data = link.get('href')
        if data.find(version) != -1:
            match = version_regex.search(data)
            if match is not None:
                # just use first occurance of matching pattern
                # Debian has two links for one version
                path = match.group()
                return path

    return None


def get_checksum_from_version_path(release, version_path):
    if "debian" in release['imagename']:
        url = release['baseURL'] + version_path + "/" + release['checksumname']
        imagename_fq = release['imagename'] + "-" + version_path + "." + release['extension']
    elif "ubuntu" in release['imagename']:
        url = release['baseURL'] + version_path + "/" + release['checksumname']
        imagename_fq = release['imagename'] + "." + release['extension']
    else:
        # not yet supported
        return None

    # print(url)
    return web_get_checksum(url, imagename_fq)


def get_correct_version_path(release, version):
    # should be needed for ubuntu with its .x ending paths
    if "debian" in release['imagename'] or "ubuntu" in release['imagename']:
        requestURL = release['baseURL']
    else:
        requestURL = release['baseURL'] + release['releasepath']

    request = requests.get(requestURL, allow_redirects=True)
    soup = BeautifulSoup(request.text, "html.parser")

    for link in soup.find_all("a"):
        data = link.get('href')
        if data.endswith('/'):
            path = data.replace('/', '')
        else:
            path = data

        if path.find(version) != -1:
            print("WARNING: Path correction necessary %s (or not found)" % path)
            return path

    return None


def get_version_metadata(release, version):
    metadata = {}

    # 1. check path
    if "debian" in release['imagename']:
        url = release['baseURL'] + version + "/" + release['imagename'] + "-" + version + "." + release['extension']
    elif "ubuntu" in release['imagename']:
        url = release['baseURL'] + "release-" + version + "/" + release['imagename'] + "." + release['extension']
    else:
        # not yet supported
        return metadata

    if url_exists(url):
        metadata['url'] = url
        if "debian" in release['imagename']:
            version_path = version
        elif "ubuntu" in release['imagename']:
            version_path = "release-" + version
    else:
        if "ubuntu" in release['imagename']:
            version_path = get_correct_version_path(release, version)
            url = release['baseURL'] + version_path + "/" + release['imagename'] + "." + release['extension']
            if url_exists(url):
                metadata['url'] = url
            else:
                print("WARNING %s does not exist" % url)
                return metadata
        else:
            print("WARNING %s does not exist" % url)
            return metadata

    # 2. get checksum
    checksum = get_checksum_from_version_path(release, version_path)
    if checksum is None:
        print("WARNING: Could not get checksum for version %s" % version)
        return {}

    metadata['checksum'] = release['algorithm'] + ":" + checksum

    # 3. extract release date from version
    release_date = version[0:4] + "-" + version[4:6] + "-" + version[6:8]
    metadata['release_date'] = release_date

    # 4. add version to metadata
    metadata['version'] = version

    return metadata


def main():
    # read configuration
    config_filename = "etc/config.yaml"

    config = config_read(config_filename, "configuration")
    if config is None:
        raise SystemExit("\nERROR: Unable to open config " + config_filename)

    # read the image sources
    sources_filename = config['sources_name']

    image_source_catalog = config_read(sources_filename, "source catalog")
    if image_source_catalog is None:
        raise SystemExit("Unable to open image source catalog " + sources_filename)

    # connect to database
    database = database_connect(config['database_name'])
    if database is None:
        print("\nERROR: Could not open database %s" % config['database_name'])
        print("\nRun \"./image-crawler.py --init-db\" to create a new database OR config check your etc/config.yaml")
        sys.exit(1)

    for source in image_source_catalog['sources']:
        for release in source['releases']:
            # pprint(release)
            print("Crawling %s %s" % (source['name'], release['name']))
            # print(get_all_versions_with_paths_from_directory(release))
            version_paths = get_all_versions_with_paths_from_directory(release)
            for version in version_paths:
                print("Getting metadata for version %s" % version)
                catalog_update = get_version_metadata(release, version)
                if not catalog_update:
                    print("WARNING: Skipping version %s due to missing metadata" % version)
                else:
                    catalog_update['name'] = source['name'] + " " + release['name']
                    catalog_update['distribution_name'] = source['name']
                    catalog_update['distribution_release'] = release['name']
                    catalog_update['release'] = release['name']

                    write_catalog_entry(database, catalog_update)

    database_disconnect(database)


if __name__ == "__main__":
    main()
