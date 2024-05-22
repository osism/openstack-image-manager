ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim 

COPY requirements.txt /src/requirements.txt
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

mkdir /wheels
python3 -m pip --no-cache-dir install -U 'pip==24.0'
python3 -m pip --no-cache-dir install -r /src/requirements.txt
python3 -m pip --no-cache-dir install 'openstack-image-manager==0.20240417.0' 

# cleanup
apt-get clean
rm -rf \
  /src \
  /tmp/* \
  /usr/share/doc/* \
  /usr/share/man/* \
  /var/lib/apt/lists/* \
  /var/tmp/*
EOF

COPY etc/images/* /etc/images/

ENTRYPOINT ["/entrypoint.sh"]
CMD ["cron","-f", "-l", "2"]
