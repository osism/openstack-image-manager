# NOTE(berendt): quick & dirty (but it works for the moment)

import logging
import os
import shutil
import patoolib
import requests
import yaml
import typer
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error
from munch import Munch
from os import listdir
from os.path import isfile, join


app = typer.Typer(add_completion=False)


@app.command()
def main(
        debug: bool = typer.Option(False, '--debug', help='Enable debug logging'),
        dry_run: bool = typer.Option(False, '--dry-run', help='Do not perform any changes'),
        images: str = typer.Option('etc/images/', help='Path to the directory containing all image files'),
        minio_access_key: str = typer.Option(None, help='Minio access key'),
        minio_secret_key: str = typer.Option(None, help='Minio secret key'),
        minio_server: str = typer.Option('minio.services.osism.tech', help='Minio server'),
        minio_bucket: str = typer.Option('openstack-image-manager', help='Minio bucket')
):
    CONF = Munch.fromDict(locals())

    if CONF.debug:
        level = logging.DEBUG
        logging.getLogger("paramiko").setLevel(logging.DEBUG)
    else:
        level = logging.INFO
        logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.basicConfig(format='%(asctime)s - %(message)s', level=level, datefmt='%Y-%m-%d %H:%M:%S')

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

    client = Minio(
        CONF.minio_server,
        access_key=CONF.minio_access_key,
        secret_key=CONF.minio_secret_key
    )

    for image in all_images:
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


if __name__ == '__main__':
    app()
