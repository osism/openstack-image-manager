#!/usr/bin/env python3
#
# image crawler
#
# the image crawler checks for new openstack ("cloud") images
# whenever a new image is detected all relevant information needed for
# maintaining an image catalog
#
# 2022-09-19 v0.1 christian.stelter@plusserver.com

import argparse
import sys
import os

from crawler.core.config import config_read
from crawler.core.database import database_connect, database_disconnect, database_initialize
from crawler.core.exporter import export_image_catalog, export_image_catalog_all
from crawler.core.main import crawl_image_sources
from crawler.git.base import clone_or_pull, update_repository


def main():
    print("\nplusserver Image Crawler v0.1\n")

    working_directory = os.getcwd()

    parser = argparse.ArgumentParser(description='checks cloud image repositories for new updates and'
                                     + ' keeps track of all images within its sqlite3 database')
    parser.add_argument('--config', type=str, required=False,
                        help='specify the config file to be used (default: etc/config.yaml)')
    parser.add_argument('--sources', type=str, required=False,
                        help='specify the sources file to be used - overrides value from config file')
    parser.add_argument('--init-db', action='store_true', required=False,
                        help='initialize image catalog database')
    parser.add_argument('--export-only', action='store_true', required=False,
                        help='export only existing image catalog')
    parser.add_argument('--updates-only', action='store_true', required=False,
                        help='check only for updates, do not export catalog')
    args = parser.parse_args()

    # read configuration
    if args.config is not None:
        config_filename = args.config
    else:
        # default
        config_filename = "etc/config.yaml"

    config = config_read(config_filename, "configuration")
    if config is None:
        raise SystemExit("\nERROR: Unable to open config " + config_filename)

    # read the image sources
    if args.sources is not None:
        sources_filename = args.sources
    else:
        sources_filename = config['sources_name']

    image_source_catalog = config_read(sources_filename, "source catalog")
    if image_source_catalog is None:
        raise SystemExit("Unable to open image source catalog " + sources_filename)

    # initialize database when run with --init-db
    if args.init_db:
        database_initialize(config['database_name'])
        sys.exit(0)

    # clone or update local repository when git is enabled
    if 'remote_repository' in config:
        clone_or_pull(config['remote_repository'], config['local_repository'])
    else:
        print("No image catalog repository configured")

    # connect to database
    database = database_connect(config['database_name'])
    if database is None:
        print("\nERROR: Could not open database %s" % config['database_name'])
        print("\nRun \"./image-crawler.py --init-db\" to create a new database OR config check your etc/config.yaml")
        sys.exit(1)

    # crawl image sources when requested
    if args.export_only:
        print("\nSkipping repository crawling")
        updated_sources = {}
    else:
        print("\nStart repository crawling")
        updated_sources = crawl_image_sources(image_source_catalog, database)

    # export image catalog
    if args.updates_only:
        print("\nSkipping catalog export")
    else:
        if updated_sources:
            print("\nExporting catalog to %s/%s" % (working_directory, config['local_repository']))
            export_image_catalog(database, image_source_catalog, updated_sources, config['local_repository'])
        else:
            if args.export_only:
                print("\nExporting all catalog files to %s/%s" % (working_directory, config['local_repository']))
                export_image_catalog_all(database, image_source_catalog, config['local_repository'])

    # push changes to git repository when configured
    if 'remote_repository' in config and updated_sources:
        update_repository(database, config['local_repository'], updated_sources)
    else:
        print("No remote repository update needed.")

    database_disconnect(database)


if __name__ == "__main__":
    main()
