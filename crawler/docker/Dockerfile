# openstack image crawler sample
#
# 2023-03-19 christian.stelter@plusserver.com

FROM python:3.10-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive
ENV DEBCONF_NOWARNINGS="yes"

# change this to your CI/CD or docker user or via --build-arg
ARG HOST_UID=1000

RUN useradd -u ${HOST_UID} -s /bin/bash -c "crawler" -d "/opt/crawler" -m crawler && \
    apt-get update && \
    apt-get --yes --quiet --no-install-recommends install sudo git openssh-client \
    libcap2-bin jq lsb-release software-properties-common curl dumb-init build-essential \
    python3-dev python3-pip python3-venv

RUN git clone --depth 1 https://github.com/osism/openstack-image-manager.git /tmp/openstack-image-manager && \
    mv /tmp/openstack-image-manager/crawler/* /opt/crawler && \
    rm -rf /tmp/openstack-image-manager && \
    cd /opt/crawler && \
    python3 -m venv .oic && \
    . .oic/bin/activate && \
    pip install --upgrade pip wheel && \
    pip install -r requirements.txt && \
    chown crawler: -R /opt/crawler && \
    echo "alias crawler='/opt/crawler/run.sh'" > /opt/crawler/.bash_aliases && \
    apt-get autoremove --purge -y && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/*

COPY files/config.yaml /opt/crawler/etc
COPY files/run.sh /opt/crawler

USER crawler
WORKDIR /workspace

VOLUME ["/workspace"]

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["bash"]
