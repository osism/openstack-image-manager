# Template Guide

**NOTE** As the Image Crawler is written in Python and the template library used is [Jinja2](https://jinja.palletsprojects.com/en/3.1.x/), you can do all the Python tricks (string functions, filters etc.) within those template for formatting extracting parts (like a base URL or similiar).

## Available variables

The catalog information is stored in the nested dict **catalog**.

### Base information

catalog contains the following information for an release (at the base level):

| Key | Value |
|---:|---|
| name | Ubuntu, Debian |
| os_version | 20.04, 22.04, 10, 11 |
| os_distro | ubuntu, debian |
| codename | focal, jammy, buster, bullseye |
| versions | dict of dicts with release version information |

You can access the information in your template as catalog['name'], catalog['os_version']. See fully blown example for Ubuntu below.

### Release version information

For each release version the following informations are accessible for your template:

| Key | Value |
|---:|---|
| name | Ubuntu 22.02, Debian 11|
| release_date | 2023-01-07, 20221205 |
| version | 20220107, 20221205-1220 |
| distribution_name | Ubuntu, Debian |
| distribution_version | 22.04, 11 |
| url | https://cloud-images.ubuntu.com/releases/jammy/release-20221201/ubuntu-22.04-server-cloudimg-amd64.img<br />https://cloud.debian.org/images/cloud/bullseye/20221205-1220debian-11-genericcloud-amd64-20221205-1220.qcow2 |
| checksum | sha256:8a814737df484d9e2f4cb2c04c91629aea2fced6799fc36f77376f0da91dba65<br />sha512:888fbb722aac52917c7aadba2af93e020ad778ced30bd864f42a463a5351ba5bbbd957b5c88d744f432f2e1766a09ce201653f03fc4d4131c3aa40fac9dacffb|

You can access the release information as catalog['versions']['20230107']['url'], catalog['versions']['20230107']['release_date'].

In a Jinja2 template you would probably loop over the versions like in

```
    versions:{% for release_version in catalog['versions'] %}
      - version: '{{ release_version }}'
        url: {{ catalog['versions'][release_version]['url'] }}
        checksum: {{ catalog['versions'][release_version]['checksum'] }}
        build_date: {{ catalog['versions'][release_version]['release_date'] }}
{%- endfor %}
```

Just like any other nested dict in Python.

## Example for Ubuntu

Fully blown example for exporting a YAML file as used by the Image Manager. This part is used for each single version of a OS version.

The name of the template is ubuntu.yaml. Image Crawler will find it under the "name" of the OS version in the templates folder. Image Crawler will iterate through all OS versions and will add all **release versions** of the OS version.

```
  - name: {{ catalog['name'] }} {{ catalog['os_version'] }}
    format: qcow2
    login: ubuntu
    min_disk: 8
    min_ram: 512
    status: active
    visibility: public
    multi: true
    meta:
      architecture: x86_64
      hypervisor_type: qemu
      hw_disk_bus: scsi
      hw_rng_model: virtio
      hw_scsi_model: virtio-scsi
      hw_qemu_guest_agent: yes
      hw_watchdog_action: reset
      replace_frequency: monthly
      hotfix_hours: 0
      uuid_validity: last-3
      provided_until: none
      os_distro: ubuntu
      os_version: '{{ catalog['os_version'] }}'
    tags: []
    latest_checksum_url: {{ metadata['baseURL'] }}{{ metadata['releasepath'] }}/{{ metadata['checksumname'] }}
    latest_url: {{ metadata['baseURL'] }}{{ metadata['releasepath'] }}/{{ metadata['imagename'] }}.{{ metadata['extension'] }}
    versions:{% for release_version in catalog['versions'] %}
      - version: '{{ release_version }}'
        url: {{ catalog['versions'][release_version]['url'] }}
        checksum: {{ catalog['versions'][release_version]['checksum'] }}
        build_date: {{ catalog['versions'][release_version]['release_date'] }}
        image_source: {{ catalog['versions'][release_version]['url'] }}
        {% set base, filename = catalog['versions'][release_version]['url'].rsplit('/', 1) -%}
        image_description: {{ base }}/unpacked/release_notes.txt
{%- endfor %}
````

The most exciting part is done in the versions part for a distribution. The for loop will walk through the versions dict part of the catalog dict (which is a nested dict) and will print out all information for the last 3 **release versions**.

### Meta Data for Images

As you might have noticed the meta data section is static (expect for the os_version). The meta data as required by the SCS standards are referenced in the following document:

* [SCS Spezifikation der Image Properties](https://github.com/SovereignCloudStack/Docs/blob/main/Design-Docs/Image-Properties-Spec.md)

The rest of the meta data used are regular OpenStack glance properties as specified in:

* [OpenStack Glance Image Properties](https://docs.openstack.org/glance/latest/admin/useful-image-properties.html)
