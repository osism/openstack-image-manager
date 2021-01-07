# openstack-image-manager

With this script it is possible to easily manage and keep up to date a
large number of images on an OpenStack environment.

We use this script to maintain the images on our public cloud Betacloud.

- [Requirements](#requirements)
- [Configuration](#configuration)
  - [Naming convention](#naming-convention)
  - [Add new image](#add-new-image)
    - [Image with regular rebuilds](#image-with-regular-rebuilds)
    - [Image without regular rebuild](#image-without-regular-rebuild)
  - [Delete image](#delete-image)
  - [Modify image properties](#modify-image-properties)
  - [Modify image tags](#modify-image-tags)
  - [Deactivate/reactivate image](#deactivatereactivate-image)
  - [Visibility](#visibility)
- [Contribute](#contribute)
- [Usage](#usage)
  - [Update and import new images](#update-and-import-new-images)
  - [Delete removed images](#delete-removed-images)
  - [Mirror images](#mirror-images)
- [Development](#development)
- [License](#license)

## Requirements

Since this script stores many images in a project, the Glance quota must be set accordingly
high or to unlimited.

```
[DEFAULT]
user_storage_quota = 1TB
```

With most storage backends it makes sense to convert the imported images directly to RAW.
This requires the following parameter for the taskflow executor.

```
[taskflow_executor]
conversion_format = raw
```

## Configuration

After a change to the configuration, validate it with `tox -e check`.

### Naming convention

* Names must be unique
* Use the full name of the product / distribution, no shortcuts

Samples:

* `Ubuntu 16.04`
* `CoreOS`

### Add new image

* Only freely accessible community images may be added.
* Currently, the decompression of images, as with CoreOS, is not supported.
* If there is no section for the product / distribution then create it
  accordingly.
* Explicitly mark `os_version` as a string to prevent evaluation as a double.
* Useful metadata keys can be found at
  https://docs.openstack.org/glance/latest/admin/useful-image-properties.html
* possible values for `os_distro` can be found in libosinfo:
  https://gitlab.com/libosinfo/osinfo-db/tree/master/data/os or
  `osinfo-query os` (omit `os_distro` if there is no meaningful value for it).
* `min_disk` and `min_ram` should always be specified (keys do not have to be
  set, by default the values are 0).
* At `login` specify the user with whom you can log in after the initial start.
  This is necessary for the generated documentation as well as later automatic
  tests.
* Special images offer the login via a password. This can be specified via the
  parameter `password`.

#### Image with regular rebuilds

```yaml
  - name: Ubuntu 16.04
    format: qcow2
    login: ubuntu
    min_disk: 8
    min_ram: 512
    status: active
    visibility: public
    multi: true
    meta:
      architecture: x86_64
      hw_disk_bus: scsi
      hw_scsi_model: virtio-scsi
      hw_watchdog_action: reset
      os_distro: ubuntu
      os_version: '16.04'
    tags: []
    versions:
      - version: '20180928'
        url: https://cloud-images.ubuntu.com/xenial/20180928/xenial-server-cloudimg-amd64-disk1.img
      - version: '20181004'
        url: https://cloud-images.ubuntu.com/xenial/20181004/xenial-server-cloudimg-amd64-disk1.img
```

This configuration creates the following images:

* ``Ubuntu 16.04 (20180928)``
* ``Ubuntu 16.04``

If a newer build is added, the following rotation takes place:

* ``Ubuntu 16.04`` becomes ``Ubuntu 16.04 (20181004)``
* the new image becomes ``Ubuntu 16.04``

#### Image without regular rebuild

```yaml
  - name: RancherOS
    format: qcow2
    login: rancher
    min_disk: 8
    min_ram: 2048
    status: active
    visibility: public
    multi: false
    meta:
      architecture: x86_64
      hw_disk_bus: scsi
      hw_scsi_model: virtio-scsi
      hw_watchdog_action: reset
    tags: []
    versions:
      - version: '1.3.0'
        url: https://github.com/rancher/os/releases/download/v1.3.0/rancheros-openstack.img
      - version: '1.4.0'
        url: https://github.com/rancher/os/releases/download/v1.4.0/rancheros-openstack.img
      - version: '1.4.1'
        url: https://github.com/rancher/os/releases/download/v1.4.1/rancheros-openstack.img
```

This configuration creates the following images:

* ``RancherOS 1.3.0``
* ``RancherOS 1.4.0``
* ``RancherOS 1.4.1``

If a new version is added, no rotation takes place. The new version is added
as ``RancherOS x.y.z``.

### Delete image

Simply remove the version of an image you want to delete or the entire
image from ``etc/images.yml``.

### Modify image properties

* Removal of properties is not yet possible
* URL, name and format can not be changed
* Any keys can be added to `meta`, these will be added to the image
* Existing keys in `meta` can be changed, the same applies to `min_disk`
  and `min_ram`

### Modify image tags

* add or remove tags to the ``tags`` list

### Deactivate/reactivate image

* deactivation: change `status` to `deactivated`
* reactivation: change `status` to `active`

### Visibility

* https://developer.openstack.org/api-ref/image/v2/index.html --> `Image visibility`

* public: set `visibility` to `public`
* community: set `visibility` to `community`
* shared: set `visibility` to `shared`
* private: set `visibility` to `private`

## Contribute

To make changes in this repository, open a pull request. To prioritize the import
of a new image send an email to `info@betacloud.de` with reference to the created
pull request.

After creating a PR, please check the result of the Travis CI and correct any
errors identified.

## Usage

The cloud environment to be used can be specified via the `--cloud` parameter. `images` is set as the default.

The path to the definitions of the images is set via the parameter `--images`. `etc/images.yml` is set as the default.

The tag for the identification of managed images is set via `--tag`. `managed_by_betacloud` is set as the default.

The debug mode can be activated via `--debug`, e.g.  `tox -- --debug`.

### Update and import new images

Simply run `tox` without parameters.

Run `tox -- --dry-run` to see what will change.

### Delete removed images

The deletion of images must be explicitly confirmed with the `--yes-i-really-know-what-i-do` parameter.

```
$ tox -- --yes-i-really-know-what-i-do
```

### Mirror images

```
$ tox -e mirror -- --server SFTP_SERVER --username SFTP_USERNAME --password SFTP_PASSWORD
```
