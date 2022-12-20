from crawler.core.database import db_get_last_checksum, write_or_update_catalog_entry
from crawler.web.generic import url_get_last_modified
from crawler.web.directory import web_get_checksum, web_get_current_image_metadata


def release_update_check(release, last_checksum):
    # works for Ubuntu, Debian
    if not release['baseURL'].endswith('/'):
        base_url = release['baseURL'] + "/"
    else:
        base_url = release['baseURL']

    # check on leading an trialing slash / for release path ?
    checksum_url = base_url + release['releasepath'] + "/" + release['checksumname']
    # works for Ubuntu, Debian
    # imagename _with_ proper extension to look for in checksum lists
    imagename = release['imagename'] + "." + release['extension']

    current_checksum = web_get_checksum(checksum_url, imagename)
    if current_checksum is None:
        print("ERROR: no matching checksum found - check image (%s) "
              "and checksum filename (%s)" % (imagename, release['checksumname']))
        return None

    current_checksum = release['algorithm'] + ":" + current_checksum

    if current_checksum != last_checksum:
        image_url = base_url + release['releasepath'] + "/" + imagename
        image_filedate = url_get_last_modified(image_url)

        image_metadata = web_get_current_image_metadata(release, image_filedate)
        if image_metadata is not None:

            update = {}
            update['release_date'] = image_metadata['release_date']
            update['url'] = image_metadata['url']
            update['version'] = image_metadata['version']
            update['checksum'] = current_checksum
            return update
        else:
            return None

    return None


def image_update_service(connection, source):
    updated_releases = []
    for release in source['releases']:
        last_checksum = db_get_last_checksum(connection, source['name'], release['name'])
        catalog_update = release_update_check(release, last_checksum)
        if catalog_update:
            print("Update found for " + source['name'] + " " + release['name'])
            print("New release " + catalog_update['version'])
            # catalog_update anreichern mit _allen_ Daten für die DB
            catalog_update['name'] = source['name'] + " " + release['name']
            catalog_update['distribution_name'] = source['name']
            catalog_update['distribution_release'] = release['name']
            catalog_update['release'] = release['name']

            write_or_update_catalog_entry(connection, catalog_update)
            updated_releases.append(release['name'])
        else:
            print("No update found for " + source['name'] + " " + release['name'])

    return updated_releases
