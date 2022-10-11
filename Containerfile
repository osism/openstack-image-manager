ARG PYTHON_VERSION=3.10
FROM python:${PYTHON_VERSION}-alpine

ARG USER_ID=45000
ARG GROUP_ID=45000

COPY . /src

WORKDIR /src

# hadolint ignore=DL3018
RUN apk add --no-cache --virtual .build-deps \
      build-base \
      git \
      libffi-dev \
      linux-headers \
      openssl-dev \
      python3-dev \
    && python3 -m pip --no-cache-dir install . \
    && mkdir -p /etc/openstack-image-manager \
    && cp /src/etc/images/*.yml /etc/openstack-image-manager \
    && rm -rf /src \
    && apk del .build-deps \
    && addgroup -g $GROUP_ID dragon \
    && adduser -D -u $USER_ID -G dragon dragon \
    && mkdir -p /input \
    && chown -R dragon: /input

USER dragon

WORKDIR /input
VOLUME ["/input"]

LABEL "org.opencontainers.image.documentation"="https://docs.osism.tech/openstack-image-manager/" \
      "org.opencontainers.image.licenses"="ASL 2.0" \
      "org.opencontainers.image.source"="https://github.com/osism/openstack-image-manager" \
      "org.opencontainers.image.url"="https://www.osism.tech" \
      "org.opencontainers.image.vendor"="OSISM GmbH"
