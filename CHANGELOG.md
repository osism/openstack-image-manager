# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file was started on Januar 28, 2026. Changes prior to this date are not included in the CHANGELOG.

## [v0.20261007.0] - 2026-10-07

### Added
- Add Ubuntu Core 26 image definition, booting via UEFI (osism/openstack-image-manager#1305)
- Add --retire-expired option to stop importing and retire images whose provided_until date has passed (osism/openstack-image-manager#1295)

### Changed
- Apply image definitions to existing images on every run, not only to new imports (osism/openstack-image-manager#1297)
- Change os_distro tag from centos to almalinux for AlmaLinux images to satisfy SCS-0102-V2 uniqueness requirements (osism/openstack-image-manager#1305)
- Run all Zuul jobs on the ubuntu-noble nodeset (osism/openstack-image-manager#1306)

### Fixed
- Tolerate managed images missing image_description or internal_version properties instead of failing with a KeyError (osism/openstack-image-manager#1296)
- Abort image sharing with an error message when the given domain does not exist instead of raising an AttributeError (osism/openstack-image-manager#1307)

### Dependencies
- patool 4.0.7 → 4.1.0 (osism/openstack-image-manager#1274)
- openstacksdk 4.17.0 → 4.20.0 (osism/openstack-image-manager#1263)

## [v0.20261005.0] - 2026-10-05

### Added
- Add `--verify-checksum` option to download and verify every image against its checksum before import (osism/openstack-image-manager#1290)

### Changed
- Retire the previous multi image in a single Glance update so a failed request cannot leave it half-retired (osism/openstack-image-manager#1300)
- Make `min_disk` optional in image definitions, deriving it from the image's virtual size (osism/openstack-image-manager#1293)

### Fixed
- Demote a superseded generic image to `oldgeneric` on rotation when a public successor would otherwise duplicate it (osism/openstack-image-manager#1276, osism/openstack-image-manager#1300)
- Accept `oldgeneric` as an `os_purpose` value in image definitions (osism/openstack-image-manager#1300)
- Verify the upstream checksum of latest versions before import and match checksums files by exact filename (osism/openstack-image-manager#1290)
- Raise `min_disk` to the virtual size of the image so Nova can boot it (osism/openstack-image-manager#1293)

## [v0.20261001.0] - 2026-10-01

### Added
- Add check_updates script and scheduled workflow to report new major versions and end-of-life images (osism/openstack-image-manager#1256)
- Add golden tests for the update script's image discovery (osism/openstack-image-manager#1255)
- Add AlmaLinux 10, Rocky Linux 10 and CentOS Stream 10 images (osism/openstack-image-manager#1260)
- Add Ubuntu 26.04 and Ubuntu 26.04 Minimal images (osism/openstack-image-manager#1260)
- Add openSUSE Leap 16.0 image (osism/openstack-image-manager#1260)
- Record the checksum an image was mirrored for as object metadata (osism/openstack-image-manager#1269)
- Add a contrib script that reports osinfo-db distros missing from the os_distro schema (osism/openstack-image-manager#1284)
- Accept os_type and os_admin_user in the image meta schema (osism/openstack-image-manager#1285)
- Add hw_cdrom_bus and hw_qemu_guest_agent to the meta schema (osism/openstack-image-manager#1292, osism/openstack-image-manager#1294)
- Add --filter and --dry-run options to the mirror script (osism/openstack-image-manager#1298, osism/openstack-image-manager#1299)
- Add --hidden-visibility option to choose the visibility of hidden images (osism/openstack-image-manager#1289)

### Changed
- Build mirror URLs from a configurable base URL instead of a MinIO bucket (osism/openstack-image-manager#1255)
- Run the update-images workflow without dry-run mode (osism/openstack-image-manager#1255)
- Refactor the update script to use pluggable handlers per image source (osism/openstack-image-manager#1255)
- Disable end-of-life openSUSE Leap 15.6 image (osism/openstack-image-manager#1260)
- Enable automatic updates for openSUSE images (osism/openstack-image-manager#1260)
- Split the mirror script's per-version step into functions with unit tests (osism/openstack-image-manager#1269)
- Check existing mirrored objects against the checksum recorded for their definition and fail on a mismatch instead of skipping (osism/openstack-image-manager#1269)
- Permit all libosinfo distro values for os_distro in the schema (osism/openstack-image-manager#1284)
- Make build_date optional and derive image_build_date from the Last-Modified header for latest versions (osism/openstack-image-manager#1286)
- Delete superseded images according to their uuid_validity as scs-0102-v2 defines it (osism/openstack-image-manager#1288)
- Try deleting superseded images before deactivating them and hide retained images with os_hidden (osism/openstack-image-manager#1289)
- Update Rocky Linux image versions (osism/openstack-image-manager#1245)
- Update Debian image versions (osism/openstack-image-manager#1246)
- Update AlmaLinux image versions (osism/openstack-image-manager#1247)
- Update CentOS Stream image versions (osism/openstack-image-manager#1248)
- Update Ubuntu image versions (osism/openstack-image-manager#1249)
- Update openSUSE image versions (osism/openstack-image-manager#1291)

### Fixed
- Skip writing image definition files in dry-run mode (osism/openstack-image-manager#1255)
- Skip disabled images in the update script so they are no longer refreshed (osism/openstack-image-manager#1258)
- Correct Garden Linux checksums for versions 1592.14, 1877.5 and 1877.6 (osism/openstack-image-manager#1270)
- Mirror openSUSE images to the object store (osism/openstack-image-manager#1260)
- Report download and unpacking failures per image version instead of aborting the mirror run, and exit non-zero when any version failed (osism/openstack-image-manager#1269)
- Add a timeout to mirror downloads so a stalled upstream cannot hang the run (osism/openstack-image-manager#1269)
- Verify mirrored images against the checksum in the definition instead of only logging a SHA512 digest (osism/openstack-image-manager#1269)
- Keep the newest image version visible when importing with --use-os-hidden (osism/openstack-image-manager#1279)
- Keep superseded images without a uuid_validity property instead of raising a KeyError (osism/openstack-image-manager#1288)
- Retain images that Glance refuses to delete as in use and report other deletion failures as errors (osism/openstack-image-manager#1289)

### Removed
- Remove MinIO mirroring and its dependencies from the update script (osism/openstack-image-manager#1255)

### Dependencies
- actions/setup-python v6 → v7 (osism/openstack-image-manager#1257)
- typer 0.27.0 → 0.27.2 (osism/openstack-image-manager#1264, osism/openstack-image-manager#1272)
- patool 4.0.5 → 4.0.7 (osism/openstack-image-manager#1271)

## [v0.20260722.0] - 2026-07-22

### Changed
- Narrow the image service proxy to the v2 API so openstacksdk 4.17 type checks pass (osism/openstack-image-manager#1207)

### Fixed
- Import local file:// images via glance-direct so configured import plugins such as raw conversion apply (osism/openstack-image-manager#1253)

### Dependencies
- typer 0.26.8 → 0.27.0 (osism/openstack-image-manager#1254)
- openstacksdk 4.10.0 → 4.17.0 (osism/openstack-image-manager#1207)

## [v0.20260714.0] - 2026-07-14

### Added
- Add aria2 prefetch import path selectable via `--prefetch`, with glance-direct fallback for stuck web-download imports and documentation in the README (osism/openstack-image-manager#1252)
- Add `--import-timeout` option to bound the overall per-image import wait (osism/openstack-image-manager#1252)

### Changed
- Pass the per-version image checksum from image definitions into the import step for aria2 verification (osism/openstack-image-manager#1252)

### Fixed
- Bound image import waits so stalled, terminally failed, or repeatedly erroring imports return instead of hanging (osism/openstack-image-manager#1252)

### Dependencies
- keystoneauth1 5.14.0 → 5.15.0 (osism/openstack-image-manager#1250)
- setuptools 82.0.1 → 83.0.0 (osism/openstack-image-manager#1250)
- stevedore 5.8.0 → 5.9.0 (osism/openstack-image-manager#1250)
- typer 0.26.7 → 0.26.8 (osism/openstack-image-manager#1250)
- typing-extensions 4.15.0 → 4.16.0 (osism/openstack-image-manager#1250)

## [v0.20260630.0] - 2026-06-30

### Added
- Automatically add opened issues and PRs to project boards (osism/openstack-image-manager#1217)
- Add checksum_url option for the latest version to reference a file containing a single digest (osism/openstack-image-manager#1202)
- Add hw_firmware_type and hw_machine_type to the meta schema (osism/openstack-image-manager#1242)
- Add the os_distro values documented by Glance, including rocky (osism/openstack-image-manager#1244)

### Changed
- Use a stable branch name for the update-images workflow (osism/openstack-image-manager#1208)
- Reformat code to comply with black 26.3.1 stable style (osism/openstack-image-manager#1209)
- Restrict checksum URL fields to HTTP(S) (osism/openstack-image-manager#1235)
- Document the content expected by checksums_url and checksum_url in the README (osism/openstack-image-manager#1235)
- Use rocky as os_distro for Rocky Linux images instead of centos (osism/openstack-image-manager#1244)
- Use a stable branch name for the gardenlinux image update workflow so one pull request is reused (osism/openstack-image-manager#1240)

### Fixed
- Handle failed checksum requests without aborting the run (osism/openstack-image-manager#1235)
- Reject non-hexadecimal strings as checksums (osism/openstack-image-manager#1235)
- Skip outdated image cleanup when image processing fails (osism/openstack-image-manager#1235)
- Fix project board automation for pull requests from forks (osism/openstack-image-manager#1241)

### Removed
- Remove setuptools as a direct runtime dependency (osism/openstack-image-manager#1243)
- Remove the undocumented os_distro value clearlinux (osism/openstack-image-manager#1244)

### Dependencies
- tabulate 0.9.0 → 0.10.0 (osism/openstack-image-manager#1162)
- setuptools 82.0.0 → 82.0.1 (osism/openstack-image-manager#1171)
- requests 2.32.5 → 2.34.2 (osism/openstack-image-manager#1194)
- patool 4.0.4 → 4.0.5 (osism/openstack-image-manager#1219)
- typer 0.24.1 → 0.26.6 (osism/openstack-image-manager#1214, osism/openstack-image-manager#1220, osism/openstack-image-manager#1221, osism/openstack-image-manager#1222, osism/openstack-image-manager#1223, osism/openstack-image-manager#1225)
- actions/checkout v6 → v7 (osism/openstack-image-manager#1238)
- paramiko 4.0.0 → 5.0.0 (osism/openstack-image-manager#1218)
- typer 0.26.6 → 0.26.7 (osism/openstack-image-manager#1227)

## [v0.20260227.0] - 2026-02-27

### Changed
- Update gardenlinux image to 1877.10 (osism/openstack-image-manager#1118)

### Dependencies
- setuptools 80.10.2 → 82.0.0 (osism/openstack-image-manager#1126)
- typer 0.21.1 → 0.24.1 (osism/openstack-image-manager#1128, osism/openstack-image-manager#1129, osism/openstack-image-manager#1132, osism/openstack-image-manager#1144)
- openstacksdk 4.9.0 → 4.10.0 (osism/openstack-image-manager#1139)

## [v0.20260128.0] - 2026-01-28

### Changed
- Updated image definitions for Garden Linux, Debian, Ubuntu, CentOS Stream and Rocky Linux (osism/openstack-image-manager#1115, osism/openstack-image-manager#1111, osism/openstack-image-manager#1110, osism/openstack-image-manager#1109, osism/openstack-image-manager#1108)

### Dependencies
- ruamel.yaml 0.18.16 → 0.19.1 (osism/openstack-image-manager#1042, osism/openstack-image-manager#1065)
- patool 4.0.2 → 4.0.4 (osism/openstack-image-manager#1031, osism/openstack-image-manager#1098)
- typer 0.20.0 → 0.21.1 (osism/openstack-image-manager#1045)
- openstacksdk 4.8.0 → 4.9.0 (osism/openstack-image-manager#1099)
- setuptools 80.9.0 → 80.10.2 (osism/openstack-image-manager#1102, osism/openstack-image-manager#1113)
- peter-evans/create-pull-request v7 → v8 (osism/openstack-image-manager#1028)

