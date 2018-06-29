# Images

[![Build Status](https://travis-ci.com/betacloud/images.svg?branch=master)](https://travis-ci.com/betacloud/images)

# Documentation

To make changes in this repository, open a pull request. To prioritize the import of a new image send an email to
`support@betacloud.io` with reference to the created pull request.

## Add image

* only freely accessible community images may be added
* if there is no section for the product / distribution then create it accordingly
* explicitly mark `os_version` as a string to prevent evaluation as a double
* useful metadata keys can be found at https://docs.openstack.org/glance/latest/admin/useful-image-properties.html
* possible values for `os_distro` can be found in libosinfo: https://gitlab.com/libosinfo/osinfo-db/tree/master/data/os or `osinfo-query os`
* `min_disk` and `min_ram` should always be specified (keys do not have to be set, by default the values are 0)

```yaml
# Fedora
[...]
- name: Fedora 28
  format: qcow2
  min_disk: 4
  min_ram: 512
  status: active
  visibility: public
  meta:
    architecture: x86_64
    hw_disk_bus: scsi
    hw_scsi_model: virtio-scsi
    os_distro: fedora
    os_version: '28'
  url: https://download.fedoraproject.org/pub/fedora/linux/releases/28/Cloud/x86_64/images/Fedora-Cloud-Base-28-1.1.x86_64.qcow2
```

### Naming convention

* names must be unique
* use the full name of the product / distribution, no shortcuts
* with one-time releases and a static image: add the release identifier
  * the image will be built once after a release and will not be updated later
* with one-time releases and a dynamic image: add the release identifier + add the build timestamp (`YYYYMMDD`)
  * the image is built after a release and rebuilt later, for example, to import updates

#### Good names

* `Ubuntu 16.04 (20180628)`
* `CoreOS 1632.3.0`

#### Bad names

* `Ubuntu 16.04 (Xenial Xerus)` or `Ubuntu 16.04`
* `Debian 8`

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
