import logging
import sys

from natsort import natsorted
from oslo_config import cfg
import requests
import yaml
from os import listdir
from os.path import isfile, join

PROJECT_NAME = 'images'
CONF = cfg.CONF
opts = [
    cfg.BoolOpt('debug', help='Enable debug logging', default=False),
    cfg.StrOpt('images', help='Path to the folder with the image files', default='etc/images/'),
    cfg.BoolOpt('latest', help='Only check the latest version', default=False)
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)

if CONF.debug:
    level = logging.DEBUG
else:
    level = logging.INFO
logging.basicConfig(format='%(asctime)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')


def check_versions(versions_to_check, versions):
    for version in versions_to_check:
        url = versions[version]['url']
        r = requests.head(url)
        logging.info("Tested URL %s: %s" % (url, r.status_code))


onlyfiles = []
for f in listdir(CONF.images):
    if isfile(join(CONF.images, f)):
        onlyfiles.append(f)

all_images = []
for file in onlyfiles:
    with open(CONF.images + file) as fp:
        data = yaml.load(fp, Loader=yaml.SafeLoader)
        images = data.get('images')
        for image in images:
            all_images.append(image)

for image in all_images:
    versions = dict()
    for version in image['versions']:
        versions[str(version['version'])] = {
            'url': version['url']
        }

        if 'os_version' in version:
            versions[version['version']]['os_version'] = version['os_version']

    sorted_versions = natsorted(versions.keys())

    if CONF.latest:
        check_versions([sorted_versions[-1]], versions)
    else:
        check_versions(sorted_versions, versions)
