import requests
import datetime

from bs4 import BeautifulSoup

from crawler.web.generic import url_fetch_content


def web_get_checksum(url, imagename):
    checksum_list = url_fetch_content(url)
    if checksum_list is None:
        return None

    for line in checksum_list.splitlines():
        if imagename in line:
            (new_checksum, filename) = line.split()
            return new_checksum

    return None


def release_build_image_url(release, versionpath, version):
    # works for Ubuntu, Debian
    if not release['baseURL'].endswith('/'):
        base_url = release['baseURL'] + "/"
    else:
        base_url = release['baseURL']

    if "debian" in release['imagename']:
        return base_url + versionpath + release['imagename'] + "-" + version + "." + release['extension']
    elif "ubuntu" in release['imagename']:
        return base_url + versionpath + release['imagename'] + "." + release['extension']
    elif "AlmaLinux" in release['imagename']:
        return base_url + release['releasepath'] + "/" + versionpath
    # we do not know this distribution
    else:
        return None


def release_get_version_from_path(release, versionpath):
    if "debian" in release['imagename']:
        if versionpath.endswith('/'):
            versionpath = versionpath.rstrip('/')
        return versionpath
    elif "ubuntu" in release['imagename']:
        if versionpath.endswith('/'):
            versionpath = versionpath.rstrip('/')
        return versionpath.replace('release-', '')
    # we do not know this distribution
    else:
        return None


def release_get_release_from_path(release, versionpath):
    if "debian" in release['imagename']:
        release_date = versionpath[0:4] + "-" + versionpath[4:6] + "-" + versionpath[6:8]
        return release_date
    elif "ubuntu" in release['imagename']:
        release_version = versionpath.replace('release-', '')
        release_date = release_version[0:4] + "-" + release_version[4:6] + "-" + release_version[6:8]
        return release_date
    # we do not know this distribution
    else:
        return None


def web_get_current_image_metadata(release, image_filedate):
    # optimistic release date assumption as in release date == upload date
    version = image_filedate.replace('-', '')

    # get directory content
    if "debian" in release['imagename'] or "ubuntu" in release['imagename']:
        requestURL = release['baseURL']
    else:
        requestURL = release['baseURL'] + release['releasepath']

    request = requests.get(requestURL, allow_redirects=True)
    soup = BeautifulSoup(request.text, "html.parser")

    for link in soup.find_all("a"):
        data = link.get('href')
        if data.find(version) != -1:
            release_version_path = data
            if "debian" in release['imagename'] or "ubuntu" in release['imagename']:
                new_version = release_get_version_from_path(release, release_version_path)
                if new_version is None:
                    return None
            else:
                new_version = version
            # check image URL?

            if "debian" in release['imagename'] or "ubuntu" in release['imagename']:
                release_date = release_get_release_from_path(release, release_version_path)
                if release_date is None:
                    return None
            else:
                release_date = image_filedate

            return ({"url": release_build_image_url(release, release_version_path, new_version),
                    "version": new_version, "release_date": release_date})

    # release is behind file date
    filedate = datetime.date(int(version[0:4]), int(version[4:6]), int(version[6:8]))

    max_days_back = 6
    days_back = 1

    while days_back <= max_days_back:
        filedate = filedate - datetime.timedelta(days=1)
        new_version = filedate.strftime("%Y%m%d")

        for link in soup.find_all("a"):
            data = link.get('href')
            if data.find(new_version) != -1:
                release_version_path = data
                if release_version_path.endswith('/'):
                    release_version_path = release_version_path.rstrip('/')
                new_version = release_get_version_from_path(release, release_version_path)

                # RELEASE DATE ?
                if new_version is None:
                    return None
                # check image URL?

                release_date = release_get_release_from_path(release, release_version_path)
                if release_date is None:
                    return None

                return ({"url": release_build_image_url(release, release_version_path, new_version),
                         "version": new_version, "release_date": release_date})

        days_back = days_back + 1

    return None
