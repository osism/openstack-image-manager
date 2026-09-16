#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

# Encrypt the object store credentials into the `- secret:` block that
# .zuul.yaml needs for openstack-image-manager-mirror-images. See the
# "Enabling the upload job once the keys exist" section of README.md.
#
# Usage:
#
#   scripts/encrypt-zuul-secret.sh <credentials-file> > secret.yaml
#   MINIO_ACCESS_KEY=... MINIO_SECRET_KEY=... scripts/encrypt-zuul-secret.sh
#
# The credentials file is the table `openstack ec2 credentials create`
# prints, i.e. rows of `| access | <value> |` and `| secret | <value> |`.
# Without a file the two values are taken from the environment instead.
#
# Available environment variables
#
# MINIO_ACCESS_KEY
# MINIO_SECRET_KEY
# SECRET_NAME
# ZUUL_PROJECT
# ZUUL_TENANT
# ZUUL_URL

# Deliberately no `set -x`, unlike the other scripts in this directory:
# every value handled here is a credential.
set -euo pipefail

SECRET_NAME=${SECRET_NAME:-SECRET_OPENSTACK_IMAGE_MANAGER}
ZUUL_PROJECT=${ZUUL_PROJECT:-osism/openstack-image-manager}
ZUUL_TENANT=${ZUUL_TENANT:-osism}
ZUUL_URL=${ZUUL_URL:-https://zuul.services.osism.tech}

die() {
    echo "$*" >&2
    exit 1
}

if ! command -v zuul-client >/dev/null 2>&1; then
    die "zuul-client not found. Install it, e.g. 'pipx install zuul-client'.
Reimplementing the encryption instead is not worth the risk: a malformed
!encrypted/pkcs1-oaep value is a Zuul configuration syntax error for the
whole project, not just for this job."
fi

# Pull one value out of the openstack CLI table. Matching on the exact
# field name keeps the 'links' row, whose value contains both '|'-free
# URLs and braces, from ever being considered.
parse_field() {
    local want=$1 file=$2

    awk -F '|' -v want="$want" '
        NF >= 3 {
            name = $2
            value = $3
            gsub(/^[ \t]+|[ \t]+$/, "", name)
            gsub(/^[ \t]+|[ \t]+$/, "", value)
            if (name == want) {
                print value
                exit
            }
        }' "$file"
}

# Encrypt one value, read from stdin, and emit only the field portion of
# zuul-client's output so both fields can share a single secret block.
#
# The value is fed through stdin rather than --infile on purpose: with
# --infile zuul-client keeps surrounding whitespace, so a trailing newline
# in the file would be encrypted into the key and authentication would then
# fail with a credential that looks correct. Reading from stdin strips it.
# printf is a shell builtin, so the plaintext never reaches any argv.
encrypt_field() {
    local field=$1

    zuul-client --zuul-url "$ZUUL_URL" encrypt \
        --tenant "$ZUUL_TENANT" \
        --project "$ZUUL_PROJECT" \
        --secret-name "$SECRET_NAME" \
        --field-name "$field" |
        sed -e '1,/^    data:$/d' -e '/^[[:space:]]*$/d'
}

if [[ $# -gt 0 ]]; then
    [[ -r $1 ]] || die "Cannot read credentials file: $1"

    ACCESS_KEY=$(parse_field access "$1")
    SECRET_KEY=$(parse_field secret "$1")

    [[ -n $ACCESS_KEY ]] || die "No 'access' row found in $1"
    [[ -n $SECRET_KEY ]] || die "No 'secret' row found in $1"
else
    ACCESS_KEY=${MINIO_ACCESS_KEY:-}
    SECRET_KEY=${MINIO_SECRET_KEY:-}

    [[ -n $ACCESS_KEY ]] || die "Pass a credentials file or set MINIO_ACCESS_KEY"
    [[ -n $SECRET_KEY ]] || die "Pass a credentials file or set MINIO_SECRET_KEY"
fi

block=$(
    printf -- '- secret:\n    name: %s\n    data:\n' "$SECRET_NAME"
    printf '%s' "$ACCESS_KEY" | encrypt_field ACCESS_KEY
    printf '%s' "$SECRET_KEY" | encrypt_field SECRET_KEY
)

# Cheap guard against a silently truncated block: anything other than both
# fields present means the output is not safe to paste into .zuul.yaml.
if [[ $(grep -c '!encrypted/pkcs1-oaep' <<<"$block") -ne 2 ]]; then
    die "Expected two encrypted fields, refusing to emit an incomplete block."
fi

printf '%s\n' "$block"

echo "
Paste the block above into .zuul.yaml, together with the semaphore and job
stanzas from README.md. Commit it only with the real encrypted values: a
placeholder breaks every pipeline for this repository." >&2
