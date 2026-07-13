# openstack-image-manager

[![PyPi version](https://badgen.net/pypi/v/openstack-image-manager/)](https://pypi.org/project/openstack-image-manager/)
[![PyPi license](https://badgen.net/pypi/license/openstack-image-manager/)](https://pypi.org/project/openstack-image-manager/)
[![Documentation](https://img.shields.io/static/v1?label=&message=documentation&color=blue)](https://osism.tech/docs/guides/operations-guide/openstack/tools/image-manager/)

Easily manage and keep up to date a large number of images on an OpenStack environment

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

## Import path (`--prefetch`)

By default images are imported with Glance's `web-download` method, where
glance-api fetches the image from its URL itself. When that fetch is slow or
flaky, the import can stall and revert to `queued`. As an alternative the image
can be downloaded locally with `aria2c` (robust multi-connection download with
retry and resume) and uploaded via the `glance-direct` import method, which runs
the same decompress/convert/store taskflow as `web-download`.

`--prefetch` selects the behaviour:

- `never` — always use `web-download` (previous default behaviour).
- `on-stuck` — **default**; use `web-download` first, and fall back to
  `aria2c` + `glance-direct` once if the web-download attempts fail.
- `always` — skip `web-download` and use `aria2c` + `glance-direct` directly.

`--import-timeout` (default `1800`) bounds the overall per-image wait, shared
across all attempts. When a definition carries a `checksum`, it is passed to
`aria2c` for verification.

The `aria2c` binary must be installed for the prefetch path, and the target
cloud must have the `glance-direct` import method enabled.

Unlike `web-download` (where glance-api fetches the image directly), the prefetch
path downloads the image to a temporary directory on the host running
`openstack-image-manager`, so that filesystem needs room for the full image
(e.g. ~345 MB for the octavia amphora image). A free-space preflight aborts before
downloading if the temporary filesystem is too small.
