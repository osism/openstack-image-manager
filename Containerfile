ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim 

COPY . /src
COPY scripts/entrypoint.sh /entrypoint.sh

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN <<EOF
set -e
set -x

# install requiered packages
apt-get update
apt-get install -y --no-install-recommends \
  build-essential \
  gcc \
  git \
  cron 

rm -f /etc/cron.d/*
rm -f /etc/cron.daily/*

# install openstack-image-manager
python3 -m pip --no-cache-dir install /src


# cleanup
apt-get clean
rm -rf \
  /src \
  /tmp/* \
  /usr/share/doc/* \
  /usr/share/man/* \
  /var/lib/apt/lists/* \
  /var/tmp/*

pip3 install --no-cache-dir pyclean==3.0.0
pyclean /usr
pip3 uninstall -y pyclean
EOF

COPY etc/images/* /etc/images/

ENTRYPOINT ["/entrypoint.sh"]
CMD ["cron","-f", "-l", "2"]
