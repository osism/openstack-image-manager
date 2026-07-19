# SPDX-License-Identifier: Apache-2.0

# Detect-and-flag: compare the image catalog against endoflife.date and report
# supported majors not yet defined + enabled images past end-of-life.

import datetime
import os
from dataclasses import dataclass, field

import yaml

ENDOFLIFE_API = "https://endoflife.date/api/{product}.json"
HTTP_TIMEOUT = 30


class EvaluationError(Exception):
    """A data-integrity violation that must abort with operational-failure status."""


@dataclass(frozen=True)
class DistroConfig:
    product: str
    lts_only: bool = False


# Keyed by etc/images/<key>.yml basename (not meta.os_distro, which is unreliable).
DISTROS = {
    "ubuntu": DistroConfig("ubuntu", lts_only=True),
    "debian": DistroConfig("debian"),
    "almalinux": DistroConfig("almalinux"),
    "rockylinux": DistroConfig("rocky-linux"),
    "centos": DistroConfig("centos-stream"),
    "opensuse": DistroConfig("opensuse"),
}


@dataclass
class CatalogEntry:
    defined: set = field(default_factory=set)
    enabled: set = field(default_factory=set)


@dataclass
class Finding:
    distro: str
    cycle: str
    release_date: str
    eol_text: str


@dataclass
class Report:
    new_majors: list = field(default_factory=list)
    eol: list = field(default_factory=list)

    def is_empty(self):
        return not self.new_majors and not self.eol


def parse_eol(raw):
    # Normalize the endoflife 'eol' field into a state.
    # Returns ("date", date) | ("not_announced", None) | ("already_eol", None).
    if raw is False:
        return ("not_announced", None)
    if raw is True:
        return ("already_eol", None)
    if isinstance(raw, str):
        return ("date", datetime.date.fromisoformat(raw))
    raise EvaluationError(f"unexpected eol value: {raw!r}")


def read_catalog(images_dir):
    catalog = {}
    for distro in DISTROS:
        path = os.path.join(images_dir, f"{distro}.yml")
        if not os.path.exists(path):
            # A configured mapping file must exist. Missing = anomaly (deleted or
            # renamed), not a reason to silently shrink the evaluated set — which
            # could otherwise report clean and close the tracking issue.
            raise EvaluationError(f"missing catalog file: {path}")
        with open(path) as fp:
            data = yaml.safe_load(fp)
        cat = CatalogEntry()
        for image in data.get("images", []):
            version = str(image.get("meta", {}).get("os_version", "")).strip()
            if not version:
                continue
            cat.defined.add(version)
            if image.get("enable", True):
                cat.enabled.add(version)
        catalog[distro] = cat
    return catalog


def _released(cycle, today):
    rel = cycle.get("releaseDate")
    return isinstance(rel, str) and datetime.date.fromisoformat(rel) <= today


def _eol_text(state, day):
    if state == "date":
        return day.isoformat()
    if state == "not_announced":
        return "not announced"
    return "date unknown"  # already_eol


def evaluate(catalog, products_data, today):
    report = Report()
    for distro, cfg in DISTROS.items():
        entry = catalog.get(distro)
        if entry is None:
            continue
        cycles = products_data.get(cfg.product)
        if not cycles:
            raise EvaluationError(f"no data for product {cfg.product}")
        by_cycle = {str(c["cycle"]): c for c in cycles}

        supported = set()
        for c in cycles:
            if not _released(c, today):
                continue
            state, day = parse_eol(c.get("eol"))
            if state == "already_eol" or (state == "date" and day <= today):
                continue
            if cfg.lts_only and not c.get("lts"):
                continue
            supported.add(str(c["cycle"]))

        if not supported:
            raise EvaluationError(f"product {cfg.product} returned no supported cycles")

        for cyc in sorted(supported - entry.defined):
            c = by_cycle[cyc]
            state, day = parse_eol(c.get("eol"))
            report.new_majors.append(
                Finding(distro, cyc, c.get("releaseDate"), _eol_text(state, day))
            )

        for cyc in sorted(entry.enabled):
            c = by_cycle.get(cyc)
            if c is None:
                raise EvaluationError(f"enabled {distro} {cyc} not found upstream")
            state, day = parse_eol(c.get("eol"))
            if state == "already_eol" or (state == "date" and day <= today):
                report.eol.append(
                    Finding(distro, cyc, c.get("releaseDate"), _eol_text(state, day))
                )
    return report


def render_markdown(report):
    lines = []
    if report.new_majors:
        lines += ["## New versions available", ""]
        for f in report.new_majors:
            lines.append(
                f"- **{f.distro}**: {f.cycle} "
                f"(released {f.release_date}, EOL {f.eol_text})"
            )
        lines.append("")
    if report.eol:
        lines += ["## End-of-life images", ""]
        for f in report.eol:
            when = (
                "(date unknown)" if f.eol_text == "date unknown" else f"on {f.eol_text}"
            )
            lines.append(
                f"- **{f.distro}**: {f.cycle} reached EOL {when} (still enabled)"
            )
        lines.append("")
    return ("\n".join(lines).strip() + "\n") if lines else ""
