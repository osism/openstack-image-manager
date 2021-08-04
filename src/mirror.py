# NOTE(berendt): quick & dirty (but it works for the moment)

import logging
import os
import shutil
import sys
from urllib.parse import urlparse

from oslo_config import cfg
from minio import Minio
from minio.error import S3Error
import patoolib
import requests
import yaml

PROJECT_NAME = 'mirror'
CONF = cfg.CONF
opts = [
    cfg.BoolOpt('debug', help='Enable debug logging', default=False),
    cfg.BoolOpt('dry-run', help='Do not really do anything', default=False),
    cfg.StrOpt('images', help='Path to the images.yml file', default='etc/images.yml'),
    cfg.StrOpt('minio-access-key', help='Minio access key'),
    cfg.StrOpt('minio-secret-key', help='Minio secret key'),
    cfg.StrOpt('minio-server', help='Minio server', default='images.osism.tech'),
    cfg.StrOpt('minio-bucket', help='Minio bucket', default='mirror')
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
    data = yaml.load(fp, Loader=yaml.SafeLoader)
    images = data.get('images', [])

client = Minio(
    CONF.minio_server,
    access_key=CONF.minio_access_key,
    secret_key=CONF.minio_secret_key
)

for image in images:
    for version in image['versions']:
        if 'source' not in version:
            continue

        logging.debug("source: %s" % version['source'])

        path = urlparse(version['source'])

        dirname = "%s/%s" % (image['shortname'], version['version'])
        filename, fileextension = os.path.splitext(os.path.basename(path.path))

        if fileextension not in ['.bz2', '.zip', '.xz']:
            filename += fileextension

        logging.debug("dirname: %s" % dirname)
        logging.debug("filename: %s" % filename)

        try:
            client.stat_object(CONF.minio_bucket, os.path.join(dirname, filename))
            logging.info("'%s' available in '%s'" % (filename, dirname))
        except S3Error:
            logging.info("'%s' not yet available in '%s'" % (filename, dirname))

            if not CONF.dry_run:
                logging.info("Downloading '%s'" % version['source'])
                response = requests.get(version['source'], stream=True)
                with open(os.path.basename(path.path), 'wb') as fp:
                    shutil.copyfileobj(response.raw, fp)
                del response

                if fileextension in ['.bz2', '.zip', '.xz']:
                    logging.info("Decompressing '%s'" % os.path.basename(path.path))
                    patoolib.extract_archive(os.path.basename(path.path), outdir='.')
                    os.remove(os.path.basename(path.path))

                logging.info("Uploading '%s' to '%s'" % (filename, dirname))

                client.fput_object(CONF.minio_bucket, os.path.join(dirname, filename), filename)
                os.remove(filename)
