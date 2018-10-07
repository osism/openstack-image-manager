# Images

[![Build Status](https://travis-ci.com/betacloud/images.svg?branch=master)](https://travis-ci.com/betacloud/images)

# Documentation

To make changes in this repository, open a pull request. To prioritize the import of a new image send an email to
`support@betacloud.io` with reference to the created pull request.

## Add new image

* only freely accessible community images may be added
* currently, the decompression of images, as with CoreOS, is not supported
* if there is no section for the product / distribution then create it accordingly
* explicitly mark `os_version` as a string to prevent evaluation as a double
* useful metadata keys can be found at https://docs.openstack.org/glance/latest/admin/useful-image-properties.html
* possible values for `os_distro` can be found in libosinfo: https://gitlab.com/libosinfo/osinfo-db/tree/master/data/os or `osinfo-query os` (omit `os_distro` if there is no meaningful value for it)
* `min_disk` and `min_ram` should always be specified (keys do not have to be set, by default the values are 0)
* At `login` specify the user with whom you can log in after the initial start. This is necessary for the generated documentation as well as later automatic tests.

### Image with regular rebuilds

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
  versions:
    20180928:
      url: https://cloud-images.ubuntu.com/xenial/20180928/xenial-server-cloudimg-amd64-disk1.img
    20181004:
      url: https://cloud-images.ubuntu.com/xenial/20181004/xenial-server-cloudimg-amd64-disk1.img
```

This configuration creates the following images:

* ``Ubuntu 16.04 (20180928)``
* ``Ubuntu 16.04``

If a newer build is added, the following rotation takes place:

* ``Ubuntu 16.04`` becomes ``Ubuntu 16.04 (20181004)``
* the new image becomes ``Ubuntu 16.04``

### Image without regular rebuild

```yaml
# RancherOS

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
  versions:
    1.3.0:
      url: https://github.com/rancher/os/releases/download/v1.3.0/rancheros-openstack.img
    1.4.0:
      url: https://github.com/rancher/os/releases/download/v1.4.0/rancheros-openstack.img
    1.4.1:
      url: https://github.com/rancher/os/releases/download/v1.4.1/rancheros-openstack.img
```

This configuration creates the following images:

* ``RancherOS 1.3.0``
* ``RancherOS 1.4.0``
* ``RancherOS 1.4.1``

If a new version is added, no rotation takes place. The new version is added as ``RancherOS x.y.z``.

### Naming convention

* names must be unique
* use the full name of the product / distribution, no shortcuts

Samples:

* `Ubuntu 16.04`
* `CoreOS`

## Delete image

* not implemented yet

## Modify image properties/tags

* management of tags not yet possible
* removal of properties is not yet possible
* URL, name and format can not be changed
* any keys can be added to `meta`, these will be added to the image
* existing keys in `meta` can be changed, the same applies to `min_disk` and `min_ram`

## Deactivate/reactivate image

* deactivation: change `status` to `deactivated`
* reactivation: change `status` to `active`

## Visibility

* https://developer.openstack.org/api-ref/image/v2/index.html --> `Image visibility`

* public: set `visibility` to `public`
* community: set `visibility` to `community`
* shared: set `visibility` to `shared`
* private: set `visibility` to `private`

# License

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
