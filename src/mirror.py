# NOTE(berendt): quick & dirty (but it works for the moment)

import logging
import os
import shutil
import sys
from urllib.parse import urlparse

from oslo_config import cfg
import paramiko
import patoolib
import requests
import yaml

PROJECT_NAME = 'mirror'
CONF = cfg.CONF
opts = [
    cfg.BoolOpt('debug', help='Enable debug logging', default=False),
    cfg.StrOpt('images', help='Path to the images.yml file', default='etc/images.yml'),
    cfg.StrOpt('server', help='SFTP server'),
    cfg.IntOpt('port', help='SFTP port', default=22),
    cfg.StrOpt('username', help='SFTP username'),
    cfg.StrOpt('password', help='SFTP password'),
    cfg.StrOpt('basepath', help='Basepath', default='/')
]
CONF.register_cli_opts(opts)
CONF(sys.argv[1:], project=PROJECT_NAME)
if CONF.debug:
    level = logging.DEBUG
    logging.getLogger("paramiko").setLevel(logging.DEBUG)
else:
    level = logging.INFO
    logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.basicConfig(format='%(asctime)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

with open(CONF.images) as fp:
    data = yaml.load(fp)
    images = data.get('images', [])

transport = paramiko.Transport(sock=(CONF.server, CONF.port))
transport.connect(username=CONF.username, password=CONF.password)
client = paramiko.SFTPClient.from_transport(transport)

for image in images:
    for version in image['versions']:
        if 'source' not in version:
            continue

        logging.debug("source: %s" % version['source'])

        path = urlparse(version['source'])

        dirname = "/%s/%s" % (image['shortname'], version['version'])
        filename = os.path.splitext(os.path.basename(path.path))[0]

        logging.debug("dirname: %s" % dirname)
        logging.debug("filename: %s" % filename)

        try:
            client.stat(os.path.join(CONF.basepath, dirname, filename))
            logging.info("'%s' available in '%s'" % (filename, dirname))
        except OSError:
            logging.info("'%s' not yet available in '%s'" % (filename, dirname))

            logging.info("Downloading '%s'" % version['source'])
            response = requests.get(version['source'], stream=True)
            with open(os.path.basename(path.path), 'wb') as fp:
                shutil.copyfileobj(response.raw, fp)
            del response

            logging.info("Decompressing '%s'" % os.path.basename(path.path))
            patoolib.extract_archive(os.path.basename(path.path), outdir='.')
            os.remove(os.path.basename(path.path))

            logging.info("Uploading '%s' to '%s'" % (filename, dirname))
            try:
                client.mkdir(dirname)
            except Exception:
                pass

            client.put(filename, os.path.join(dirname, filename))
            os.remove(filename)
