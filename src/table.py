import sys

from oslo_config import cfg
from os import listdir
from os.path import isfile, join
import tabulate
import yaml

PROJECT_NAME = 'table'
CONF = cfg.CONF
opts = [
    cfg.StrOpt('images', help='Path to the folder with the image files', default='etc/images/')
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)

onlyfiles = []
for f in listdir(CONF.images):
    if isfile(join(CONF.images, f)):
        onlyfiles.append(f)

all_images = []
for file in onlyfiles:
    with open(join(CONF.images, file)) as fp:
        data = yaml.load(fp, Loader=yaml.SafeLoader)
        images = data.get('images')
        for image in images:
            all_images.append(image)

data = []
for image in all_images:
    data.append([image['name'], image['login'], image.get('password', '')])

result = tabulate.tabulate(
    sorted(data),
    headers=['Name', 'Login user', 'Password'],
    tablefmt="rst"
)
print(result)
