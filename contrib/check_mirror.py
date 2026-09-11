# SPDX-License-Identifier: Apache-2.0

# Read-only check of the object store against the catalog. Every version the
# mirror step handles must be retrievable from its mirror_url, because that is
# what main.py hands Glance -- and it is fetched with no credentials, so that
# is how this probes. A gap is reported as pending mirror when upstream is
# still reachable, and as unmirrorable when it is not.

import sys
import time
from dataclasses import dataclass, field

import requests
import typer
from loguru import logger

from contrib.mirror import iter_mirrorable

app = typer.Typer()

HTTP_TIMEOUT = 30

# A full pass is close to 80 requests against essentially one host, so a
# single TLS reset or stalled connection must not fail the whole run. Retry
# only a transport failure -- an HTTP status is a verdict and is never
# retried.
RETRY_ATTEMPTS = 3
RETRY_SLEEP_SECONDS = (1, 2)

# What a fetch of the bytes may answer: 200 for a body, 206 when the server
# honours the one-byte range. Following redirects and requiring this at the end
# of the chain is what stops a 302 to a gone target counting as retrievable --
# the gardenlinux upstream urls really do answer 302.
FETCHED = (200, 206)
# What main.py:991 accepts from its own non-following HEAD of the url it is
# about to hand Glance. Applies to mirror_url only: a 301 there fails the
# import however servable the bytes are. Upstream faces no such gate, since
# only mirror.py fetches it, with allow_redirects=True (in mirror_version() in
# contrib/mirror.py).
MANAGER_ACCEPTS = (200, 302)

EXIT_CLEAN = 0
EXIT_UNMIRRORABLE = 1
# 2 is operational: it is check_updates.py's convention for a run that reached
# no verdict, and typer's own exit code for a usage error. Pending is 3 so that
# a mistyped option can never be read as a verdict.
EXIT_OPERATIONAL = 2
EXIT_PENDING = 3


class OperationalError(Exception):
    """The run could not reach a verdict."""


@dataclass(frozen=True)
class Finding:
    name: str
    shortname: str
    version: str
    mirror_url: str
    mirror_status: str
    upstream_status: str


@dataclass
class Report:
    pending: list = field(default_factory=list)
    unmirrorable: list = field(default_factory=list)

    def is_empty(self):
        return not self.pending and not self.unmirrorable


def _chain(response):
    """Describe the status chain, e.g. '403' or '302 -> 200'."""
    codes = [str(hop.status_code) for hop in response.history]
    codes.append(str(response.status_code))
    return " -> ".join(codes)


def _with_retries(url, probe):
    """Run probe() up to RETRY_ATTEMPTS times, retrying only a transport failure.

    An HTTP status is a verdict and is returned immediately, never retried.
    Only requests.RequestException -- a connection reset, timeout, or similar
    transport hiccup -- triggers a retry, with a short backoff in between.
    OperationalError is raised only once every attempt has failed.
    """
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return probe()
        except requests.RequestException as exc:
            if attempt == RETRY_ATTEMPTS - 1:
                raise OperationalError(f"cannot probe {url}: {exc}")
            time.sleep(RETRY_SLEEP_SECONDS[attempt])


def fetchable(url):
    """Read one byte of url's body, following redirects.

    Returns (bytes arrived, status chain as text). Only a FETCHED status is
    read at all -- a 403's error payload is irrelevant. A FETCHED status with
    an empty body means the server answered but never sent bytes, which is
    not retrievable either; the returned text is then annotated, e.g.
    "206 (empty body)". A transport failure while reading the body is
    operational, same as one while reading the headers -- it says nothing
    about the object. An HTTP status is a verdict, including 403, which is
    what Hetzner answers for a key that does not exist.
    """

    def probe():
        response = requests.get(
            url,
            headers={"Range": "bytes=0-0"},
            allow_redirects=True,
            stream=True,
            timeout=HTTP_TIMEOUT,
        )
        try:
            status = _chain(response)
            arrived = response.status_code in FETCHED
            if arrived:
                chunk = next(response.iter_content(chunk_size=1), b"")
                if not chunk:
                    arrived = False
                    status = f"{status} (empty body)"
        finally:
            response.close()
        return arrived, status

    return _with_retries(url, probe)


def accepted_by_manager(url):
    """Reproduce main.py's own pre-import check: a non-following HEAD.

    Returns (accepted, status). Only meaningful for a url the manager hands
    Glance, i.e. mirror_url.
    """

    def probe():
        response = requests.head(url, allow_redirects=False, timeout=HTTP_TIMEOUT)
        return response.status_code in MANAGER_ACCEPTS, str(response.status_code)

    return _with_retries(url, probe)


def probe_mirror(url):
    """Both conditions the mirrored object has to satisfy.

    The manager refuses a status outside MANAGER_ACCEPTS before it ever starts
    the import, and Glance then has to actually receive bytes. Neither implies
    the other: a healthy object answers 200 to HEAD and 206 to a ranged GET.
    """
    accepted, head_status = accepted_by_manager(url)
    arrived, get_status = fetchable(url)

    status = f"HEAD {head_status}, GET {get_status}"
    if accepted and arrived:
        return True, status
    if arrived and not accepted:
        return False, f"{status} (the manager refuses a {head_status})"
    return False, status


def evaluate(images_dir):
    report = Report()
    for image, version in iter_mirrorable(images_dir):
        retrievable, status = probe_mirror(version["mirror_url"])
        if retrievable:
            logger.debug(f"{image['shortname']} {version['version']}: {status}")
            continue

        # Upstream is fetched only by mirror_version() in contrib/mirror.py,
        # which follows redirects, so any chain ending in bytes counts -- a
        # 301 here is not a problem.
        upstream_retrievable, upstream_status = fetchable(version["url"])
        finding = Finding(
            name=image["name"],
            shortname=image["shortname"],
            version=str(version["version"]),
            mirror_url=version["mirror_url"],
            mirror_status=status,
            upstream_status=upstream_status,
        )
        if upstream_retrievable:
            report.pending.append(finding)
        else:
            report.unmirrorable.append(finding)
    return report


def render(report):
    lines = []
    if report.unmirrorable:
        lines += [
            "Unmirrorable -- mirror not retrievable, upstream not retrievable "
            "either, so no mirror run can fill these:",
            "",
        ]
        for finding in report.unmirrorable:
            lines.append(
                f"  {finding.name} {finding.shortname} {finding.version}: "
                f"mirror {finding.mirror_status}, upstream {finding.upstream_status}"
            )
            lines.append(f"    {finding.mirror_url}")
        lines.append("")
    if report.pending:
        # Never "missing" or "no copy": a 403 cannot tell absence apart from an
        # object that exists and lost its public read permission.
        lines += [
            "Pending mirror -- mirror not retrievable, upstream retrievable:",
            "",
        ]
        for finding in report.pending:
            lines.append(
                f"  {finding.name} {finding.shortname} {finding.version}: "
                f"mirror {finding.mirror_status}"
            )
            lines.append(f"    {finding.mirror_url}")
        lines.append("")
    return ("\n".join(lines).strip() + "\n") if lines else ""


@app.command()
def main(
    images: str = typer.Option("etc/images/", help="Directory with image definitions"),
    debug: bool = typer.Option(False, help="Enable debug logging"),
):
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if debug else "INFO")

    try:
        report = evaluate(images)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure here reached no verdict
        logger.error(f"operational failure: {exc}")
        raise typer.Exit(code=EXIT_OPERATIONAL)

    if report.is_empty():
        logger.info("every mirrored object the catalog references is retrievable")
        raise typer.Exit(code=EXIT_CLEAN)

    sys.stdout.write(render(report))

    if report.unmirrorable:
        raise typer.Exit(code=EXIT_UNMIRRORABLE)
    raise typer.Exit(code=EXIT_PENDING)


if __name__ == "__main__":
    app()
