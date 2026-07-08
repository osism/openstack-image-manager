# openstack-image-manager

[![PyPi version](https://badgen.net/pypi/v/openstack-image-manager/)](https://pypi.org/project/openstack-image-manager/)
[![PyPi license](https://badgen.net/pypi/license/openstack-image-manager/)](https://pypi.org/project/openstack-image-manager/)
[![Documentation](https://img.shields.io/static/v1?label=&message=documentation&color=blue)](https://osism.tech/docs/guides/operations-guide/openstack/tools/image-manager/)

Easily manage and keep up to date a large number of images on an OpenStack environment

## Usage

By default `openstack-image-manager` (and `osism manage images`, which uses it
in the backend) only shows a **preview** of the images that would be uploaded,
a rough estimate of how long that would take and the command to actually
perform the upload. It does not connect to OpenStack and makes no changes:

```
openstack-image-manager
```

To actually import the images, add `--upload`:

```
openstack-image-manager --upload
```

See the [documentation](https://osism.tech/docs/guides/operations-guide/openstack/tools/image-manager/)
for all available options.

## Upstream checksum fields

Image versions using the `latest` pointer must specify where to find the
upstream checksum, using exactly one of these two fields:

- `checksums_url` — URL of a checksums file that contains the image filename,
  e.g. the `SHA256SUMS` manifest published by Ubuntu. Lines have the form
  `<digest> <filename>`; the line matching the image filename is used.
- `checksum_url` — URL of a checksum file that contains a single bare digest
  and nothing else, e.g. the `.sha512` sidecar files published by Alpine. Use
  this when the checksum file does not contain the image filename.

Supported digests are MD5, SHA-1, SHA-256 and SHA-512 (hex-encoded). The
checksum URLs must be HTTP(S).
