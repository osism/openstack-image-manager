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

## Mirroring images to the object store

Versions that carry a `mirror_url` are expected to be retrievable from the
`osism` bucket on `nbg1.your-objectstorage.com` — `mirror_url`, not `url`, is
what the manager hands to Glance for import.

**How an object gets into the store.** Once a definition change merges to
`main`, the `post` pipeline is designed to run the
`openstack-image-manager-mirror-images` job: `tox -e mirror` uploads every
object the catalog references that the store lacks, and the same job then
runs `tox -e check-mirror` to confirm each object is anonymously retrievable.
`periodic-daily` re-runs the check every day and, once the upload job is
enabled there too, re-uploads anything that should be present but is not
retrievable — including an object that arrived by some other route. As of
this writing `openstack-image-manager-mirror-images` is not yet committed
(see below); only the check half of this lifecycle is live.

**Reading a red check.** `tox -e check-mirror` (`contrib/check_mirror.py`)
walks the catalog and reports its findings in two classes:

- *pending mirror* — the mirror is not retrievable while upstream still is,
  so an upload is owed.
- *unmirrorable* — neither the mirror nor upstream is retrievable, so the
  pinned `url` must be updated before any upload can fix this.

"Not retrievable" is the strongest claim available: the object store answers
`403` both for an object that was never uploaded and for one that exists but
lost its public read permission, and the fix differs (an upload versus a
permissions change) — so neither the checker nor this README calls an object
"missing" or "absent".

`openstack-image-manager-check-upstream` walks the *whole* catalog, not only
what the change under review touched. So once any one version is both
unmirrored and its upstream `url` has rotted, that single pin blocks the
`check` pipeline for every subsequent PR that touches `etc/images/*.yml` —
including renovate's automated ones — until it is fixed, regardless of what
those PRs actually changed. The PR that bumps the dead pin is what clears it
again.

Exit codes of `tox -e check-mirror`: `0` clean, `1` at least one unmirrorable
version, `2` the run reached no verdict (an operational failure, or a usage
error — typer's own exit code for a usage error is also `2`), `3` pending
mirror only.

The mirror is probed twice: a non-following `HEAD`, reproducing the gate that
`main.py:991` applies before import (which accepts only `200` and `302`), and
a ranged `GET` with redirects followed, requiring that bytes actually arrive
(`200` or `206`). A healthy object reads `HEAD 200, GET 206`. Upstream is
probed once, with a ranged `GET` that follows redirects, because only
`contrib/mirror.py` fetches it, and that fetch follows redirects too.

**Running the mirror by hand**, for someone holding the object store
credentials:

```console
$ export MINIO_ACCESS_KEY=... MINIO_SECRET_KEY=...
$ tox -e mirror
$ tox -e check-mirror
```

**Triggering the Zuul job manually.** There is no `workflow_dispatch`
equivalent. Enqueueing `openstack-image-manager-mirror-images` (once it
exists, see below) takes Zuul admin rights and `zuul-client enqueue-ref`
against the `post` pipeline for `osism/openstack-image-manager` — take the
exact invocation from `zuul-client enqueue-ref --help`.

**Enabling the upload job once the keys exist.** The two keys are the access
key and secret key for the `osism` bucket on `nbg1.your-objectstorage.com`.
Encrypt them for this project with `zuul-client encrypt` (check the flags
against `zuul-client encrypt --help`; the project's public key is served by
the Zuul API on the OSISM Zuul, `https://zuul.services.osism.tech` — its
build URLs are of the form
`https://zuul.services.osism.tech/t/osism/buildset/<id>`, but this README does
not assert the exact key-endpoint path, so check `zuul-client encrypt --help`
or the Zuul documentation for that), then add the block below to
`.zuul.yaml`. The secret name, data keys and binding deliberately match the
job removed in `3c21cc5`, so any earlier runbook for it still applies.

> **Warning:** do not commit this block as-is. A placeholder
> `!encrypted/pkcs1-oaep` value, like the ones below, is a Zuul
> **configuration syntax error for the whole project** — it breaks every
> pipeline for this repo, not just this job. Commit it only once the
> placeholders are replaced with real encrypted values.

```yaml
- secret:
    name: SECRET_OPENSTACK_IMAGE_MANAGER
    data:
      ACCESS_KEY: !encrypted/pkcs1-oaep
        - <output of zuul-client encrypt>
      SECRET_KEY: !encrypted/pkcs1-oaep
        - <output of zuul-client encrypt>

- semaphore:
    name: semaphore-openstack-image-manager-mirror-images
    max: 1

- job:
    name: openstack-image-manager-mirror-images
    description: |
      Upload every object the catalog references and the store lacks, then
      confirm each one is anonymously retrievable.
    semaphores:
      - name: semaphore-openstack-image-manager-mirror-images
    allowed-projects: osism/openstack-image-manager
    nodeset: ubuntu-noble-large
    timeout: 5400
    pre-run: playbooks/pre-mirror-images.yml
    run: playbooks/mirror-images.yml
    secrets:
      - name: secret
        secret: SECRET_OPENSTACK_IMAGE_MANAGER
```

...plus the job added to the `post` pipeline (branch `main`) and to
`periodic-daily`, alongside the existing `openstack-image-manager-check-mirror`
job there. `.zuul.yaml` has no `post:` pipeline section today, so this adds
one to the `project:` stanza, shaped like its existing `check:` and
`periodic-daily:` sections:

```yaml
- project:
    merge-mode: squash-merge
    default-branch: main
    check:
      jobs:
        - ...             # unchanged
    post:
      jobs:
        - openstack-image-manager-mirror-images:
            branches: main
    periodic-daily:
      jobs:
        - flake8
        - mypy
        - openstack-image-manager-check-mirror
        - openstack-image-manager-integration-test
        - openstack-image-manager-mirror-images
        - python-black
        - tox:
            vars:
              tox_envlist: test
              tox_extra_args: -- test/unit
        - yamllint
```
