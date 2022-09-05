============
Requirements
============

OpenStack image service
=======================

.. note:: See upstream glance documentation for more details: `<https://docs.openstack.org/glance/yoga/configuration/sample-configuration.html>`_

Since this script stores many images in a project, the Glance quota 
must be set accordingly high or to unlimited.

.. code-block:: ini

    [DEFAULT]
    user_storage_quota = 1TB

With most storage backends it makes sense to convert the imported images directly 
to RAW. This requires the following parameter for the image import workflow.

.. code-block:: ini

    [taskflow_executor]
    conversion_format = raw

    [image_import_opts]
    image_import_plugins = ['image_decompression', 'image_conversion']

    [image_conversion]
    output_format = raw

S3 storage backend
==================

If the mirror functionality is used, an S3 storage backend is required. The use
of the mirror functionality is optional and is not used by default.

Therefore, no S3 storage backend is required to use the OpenStack Image Manager.
