# Dockerfile Example

Example Dockerfile for using the image crawler in a container (CI/CD pipeline).

# Build

Set your HOST_UID to the UID of the user that runs the container so
that you are able to write in the directores of that user.

For example: the UID of the user jenkins on your CI/CD system.

It will be mapped to the user crawler within the container.

```
$ docker build --build-arg HOST_UID=$(id -u) --tag image-crawler:v0.2 .
```

# Usage

After building your image you can run it as

```
$ docker run --rm -it -h oicc -v $(pwd):/workspace image-crawler:v0.2 bash
```

There is an alias for the crawler:

```
crawler@oicc:/workspace$ alias
alias crawler='/opt/crawler/run.sh'

crawler@oicc:/workspace$ crawler --init-db

plusserver Image Crawler v0.2

Successfully read configuration from /opt/crawler/etc/config.yaml
Successfully read source catalog from /opt/crawler/etc/image-sources.yaml
New database created under /workspace/image-catalog.db
```


The software and initial config is located in /opt/crawler and you will
start in the directory /workspace which your mounted directory of your
docker host.

Files like the image-catalog.db and the exported image-catalog files shall
be created in here so that you can copy the results of any run after
running the crawler to a location you hold your image catalog (git repo)
or your image-catalog.db (we store it in a local versioned S3 bucket).

Modify the sample config.yaml to suit your needs.

```
database_name: "/workspace/image-catalog.db"
sources_name: "/opt/crawler/etc/image-sources.yaml"
template_path: "/opt/crawler/templates"
local_repository: "/workspace/image-catalog"
```

This shall only be an inspiration.
