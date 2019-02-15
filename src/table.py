import os
import sys

from oslo_config import cfg
import tabulate
import yaml

PROJECT_NAME='table'
CONF = cfg.CONF
opts = [
  cfg.StrOpt('images', help='Path to the images.yml file', default='etc/images.yml')
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)

with open(CONF.images) as fp:
    images = yaml.load(fp)

data = []
for image in images:
    data.append([image['name'], image['login'], image.get('password', '')])

print(tabulate.tabulate(sorted(data), headers=['Name', 'Login user', 'Password'], tablefmt="rst"))
