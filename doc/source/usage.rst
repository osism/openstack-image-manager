=====
Usage
=====

.. code-block:: bash

  $ tox -- --help
  [...]
  usage: manage [-h] [--cloud CLOUD] [--config-dir DIR] [--config-file PATH] [--deactivate] [--debug] [--delete] [--dry-run] [--hide] [--images IMAGES] [--latest] [--name NAME] [--nodeactivate]
                [--nodebug] [--nodelete] [--nodry-run] [--nohide] [--nolatest] [--nouse-os-hidden] [--noyes-i-really-know-what-i-do] [--tag TAG] [--use-os-hidden] [--yes-i-really-know-what-i-do]

  optional arguments:
    -h, --help            show this help message and exit
    --cloud CLOUD         Cloud name in clouds.yaml
    --config-dir DIR      Path to a config directory to pull `*.conf` files from. This file set is sorted, so as to provide a predictable parse order if individual options are over-ridden. The set is
                          parsed after the file(s) specified via previous --config-file, arguments hence over-ridden options in the directory take precedence. This option must be set from the command-
                          line.
    --config-file PATH    Path to a config file to use. Multiple config files can be specified, with values in later files taking precedence. Defaults to None. This option must be set from the
                          command-line.
    --deactivate          Deactivate images that should be deleted
    --debug               Enable debug logging
    --delete              Delete images that should be delete
    --dry-run             Do not really do anything
    --hide                Hide images that should be deleted
    --images IMAGES       Path to the directory containing all image files
    --latest              Only import the latest version of images from type multi
    --name NAME           Image name to process
    --nodeactivate        The inverse of --deactivate
    --nodebug             The inverse of --debug
    --nodelete            The inverse of --delete
    --nodry-run           The inverse of --dry-run
    --nohide              The inverse of --hide
    --nolatest            The inverse of --latest
    --nouse-os-hidden     The inverse of --use-os-hidden
    --noyes-i-really-know-what-i-do
                          The inverse of --yes-i-really-know-what-i-do
    --tag TAG             Name of the tag used to identify managed images
    --use-os-hidden       Use the os_hidden property
    --yes-i-really-know-what-i-do
                          Really delete images

The cloud environment to be used can be specified via the ``--cloud`` parameter. The default-value is: `openstack`.

The path of the ``clouds.yaml`` file to be used can be set via the environment variable ``OS_CLIENT_CONFIG_FILE``.

OS_CLIENT_CONFIG_FILE

The path to the definitions of the images is set via the parameter ``--images``. The default-value is: `etc/images.yml`.

The tag for the identification of managed images is set via ``--tag``. The default-value is: `managed_by_osism`.

The debug mode can be activated via ``--debug``, e.g.  ``tox -- --debug``.

Validate config
===============

After a change to the configuration, validate it with ``tox -- --dry-run``.

Update and import new images
============================

Simply run ``tox`` without parameters.

Run ``tox -- --dry-run`` to see what will change.

Outdated image handling
=======================

.. note:: By default outdated images are renamed but will stay accessable. There are 3 ways to handle outdated Images: hide, deactivate + delete

Hide images
-----------

.. code-block:: bash

  $ tox -- --hide

Deactivate images
-----------------

.. code-block:: bash

  $ tox -- --deactivate

Delete images
-------------

The deletion of images must be explicitly confirmed with the ``--yes-i-really-know-what-i-do`` parameter.

.. code-block:: bash

    $ tox -- --delete --yes-i-really-know-what-i-do

Mirror images
=============

.. code-block:: bash

    $ tox -e mirror -- --server SFTP_SERVER --username SFTP_USERNAME --password SFTP_PASSWORD

Change the tag of the managed images
====================================

* old tag: ``managed_by_betacloud``
* new tag: ``managed_by_osism``

.. code-block:: bash

    openstack --os-cloud service image list --tag managed_by_betacloud -f value -c ID | tr -d '\r' | xargs -n1 openstack --os-cloud service image set --tag managed_by_osism
    openstack --os-cloud service image list --tag managed_by_betacloud -f value -c ID | tr -d '\r' | xargs -n1 openstack --os-cloud service image unset --tag managed_by_betacloud
