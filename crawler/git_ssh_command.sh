#!/usr/bin/env bash
SSH_PRIV_KEY=/secrets/id_rsa_git_access_key
ssh -i $SSH_PRIV_KEY -o IdentitiesOnly=yes "$@"
