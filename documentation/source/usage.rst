.. _usage:

=====
Usage
=====

The cloud environment to be used can be specified via the ``--cloud`` parameter. The default-value is: `images`.

The path to the definitions of the images is set via the parameter ``--images``. The default-value is: `etc/images.yml`.

The tag for the identification of managed images is set via ``--tag``. The default-value is: `managed_by_osism`.

The debug mode can be activated via ``--debug``, e.g.  ``tox -- --debug``.

Update and import new images
============================

Simply run ``tox`` without parameters.

Run ``tox -- --dry-run`` to see what will change.

Delete removed images
=====================

The deletion of images must be explicitly confirmed with the ``--yes-i-really-know-what-i-do`` parameter.

.. code-block:: bash

    $ tox -- --yes-i-really-know-what-i-do

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
