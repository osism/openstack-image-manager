from jinja2 import Template
import os

from crawler.core.database import read_release_from_catalog


def export_image_catalog(connection, sources_catalog, updated_sources, local_repository):
    # "smart" export - only releases with updates will be written
    # create directory (once) - only necessary when not created by git clone
    if not os.path.exists(local_repository):
        try:
            print("Creating repository directory (%s)" % local_repository)
            os.makedirs(local_repository)
        except os.error as error:
            raise SystemExit("FATAL: Creating directory %s failed with %s" % (local_repository, error))

    for source in sources_catalog['sources']:
        if source['name'] in updated_sources:
            distribution = source['name']
            print("Exporting image catalog for " + distribution)
            header_file = open("templates/header.yml")
            catalog_export = header_file.read()
            header_file.close()

            image_template_filename = "templates/" + distribution.lower().replace(" ", "_") + ".yml.j2"
            image_template_file = open(image_template_filename, "r")
            image_template = Template(image_template_file.read())
            image_template_file.close()

            for release in source['releases']:
                # TODO check empty catalog (still necessary after add updated sources?)
                release_catalog = read_release_from_catalog(connection, distribution, release['name'])
                release_catalog['name'] = distribution
                release_catalog['os_distro'] = distribution.lower()
                release_catalog['os_version'] = release['name']

                catalog_export = catalog_export + image_template.render(catalog=release_catalog,
                                                                        metadata=release) + "\n"

            image_catalog_export_filename = local_repository + "/" + distribution.lower().replace(" ", "_") + ".yml"
            # TODO error handling
            image_catalog_export_file = open(image_catalog_export_filename, "w")
            image_catalog_export_file.write(catalog_export)
            image_catalog_export_file.close()


def export_image_catalog_all(connection, sources_catalog, local_repository):
    # export all releases - used with --export-only
    # create directory (once) - only necessary when not created by git clone
    if not os.path.exists(local_repository):
        try:
            print("Creating repository directory (%s)" % local_repository)
            os.makedirs(local_repository)
        except os.error as error:
            raise SystemExit("FATAL: Creating directory %s failed with %s" % (local_repository, error))

    for source in sources_catalog['sources']:
        distribution = source['name']
        print("Exporting image catalog for " + distribution)
        header_file = open("templates/header.yml")
        catalog_export = header_file.read()
        header_file.close()

        image_template_filename = "templates/" + distribution.lower().replace(" ", "_") + ".yml.j2"
        image_template_file = open(image_template_filename, "r")
        image_template = Template(image_template_file.read())
        image_template_file.close()

        for release in source['releases']:
            # TODO check empty catalog (still necessary after add updated sources?)
            release_catalog = read_release_from_catalog(connection, distribution, release['name'])
            release_catalog['name'] = distribution
            release_catalog['os_distro'] = distribution.lower()
            release_catalog['os_version'] = release['name']
            release_catalog['codename'] = release['codename']

            catalog_export = catalog_export + image_template.render(catalog=release_catalog, metadata=release) + "\n"

        image_catalog_export_filename = local_repository + "/" + distribution.lower().replace(" ", "_") + ".yml"
        # TODO error handling
        image_catalog_export_file = open(image_catalog_export_filename, "w")
        image_catalog_export_file.write(catalog_export)
        image_catalog_export_file.close()
