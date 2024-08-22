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
  git

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

ENV USER=oim
ENV UID=8000
ENV GROUP=oim
ENV GID=8000

RUN addgroup --gid ${GID} ${GROUP} && adduser --shell /bin/bash --gid ${GID} --uid ${UID} ${USER}
RUN mkdir -p /oim/src
RUN chown -R oim:oim /oim

USER oim

ENTRYPOINT ["/entrypoint.sh"]
