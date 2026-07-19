# SPDX-License-Identifier: Apache-2.0

import datetime
import os
import shutil
import tempfile
import unittest

import contrib.check_updates as cu

TODAY = datetime.date(2026, 6, 1)

UBUNTU = [
    {"cycle": "26.04", "releaseDate": "2026-04-23", "eol": "2031-04-30", "lts": True},
    {"cycle": "25.10", "releaseDate": "2025-10-09", "eol": "2026-07-01", "lts": False},
    {"cycle": "24.04", "releaseDate": "2024-04-25", "eol": "2029-04-25", "lts": True},
    {"cycle": "22.04", "releaseDate": "2022-04-21", "eol": "2027-04-01", "lts": True},
]
OPENSUSE = [
    {"cycle": "16.0", "releaseDate": "2025-10-01", "eol": "2027-10-31", "lts": None},
    {"cycle": "15.6", "releaseDate": "2024-06-12", "eol": "2026-04-30", "lts": None},
]
DEBIAN = [
    {"cycle": "13", "releaseDate": "2025-08-09", "eol": "2028-08-09", "lts": True},
    {"cycle": "12", "releaseDate": "2023-06-10", "eol": "2028-06-30", "lts": True},
]


def entry(defined, enabled=None):
    return cu.CatalogEntry(
        defined=set(defined), enabled=set(enabled if enabled is not None else defined)
    )


class EvaluateTest(unittest.TestCase):
    def test_ubuntu_lts_filter(self):
        catalog = {"ubuntu": entry(["22.04", "24.04"])}
        report = cu.evaluate(catalog, {"ubuntu": UBUNTU}, TODAY)
        cycles = {f.cycle for f in report.new_majors}
        self.assertEqual(cycles, {"26.04"})  # not 25.10 (non-LTS), not 25.04

    def test_opensuse_both_signals(self):
        catalog = {"opensuse": entry(["15.6"])}
        report = cu.evaluate(catalog, {"opensuse": OPENSUSE}, TODAY)
        self.assertEqual({f.cycle for f in report.new_majors}, {"16.0"})
        self.assertEqual({f.cycle for f in report.eol}, {"15.6"})

    def test_clean_distro(self):
        catalog = {"debian": entry(["12", "13"])}
        report = cu.evaluate(catalog, {"debian": DEBIAN}, TODAY)
        self.assertTrue(report.is_empty())

    def test_disabled_not_eol_flagged(self):
        # 15.6 defined but disabled -> no EOL finding; 16.0 still a new major.
        catalog = {"opensuse": entry(["15.6"], enabled=[])}
        report = cu.evaluate(catalog, {"opensuse": OPENSUSE}, TODAY)
        self.assertEqual(report.eol, [])
        self.assertEqual({f.cycle for f in report.new_majors}, {"16.0"})

    def test_future_release_not_flagged(self):
        product = [
            {
                "cycle": "24.04",
                "releaseDate": "2024-04-25",
                "eol": "2029-04-25",
                "lts": True,
            },
            {
                "cycle": "99.04",
                "releaseDate": "2027-01-01",
                "eol": "2032-01-01",
                "lts": True,
            },
        ]
        catalog = {"ubuntu": entry(["24.04"])}
        report = cu.evaluate(catalog, {"ubuntu": product}, TODAY)
        self.assertEqual(report.new_majors, [])  # 99.04 unreleased

    def test_boolean_eol_both_values(self):
        product = [
            {"cycle": "a", "releaseDate": "2020-01-01", "eol": False, "lts": True},
            {"cycle": "b", "releaseDate": "2019-01-01", "eol": True, "lts": True},
        ]
        catalog = {"ubuntu": entry(["b"])}  # b defined+enabled
        report = cu.evaluate(catalog, {"ubuntu": product}, TODAY)
        self.assertEqual({f.cycle for f in report.new_majors}, {"a"})
        self.assertEqual({f.cycle for f in report.eol}, {"b"})
        eol_a = next(f for f in report.new_majors if f.cycle == "a")
        self.assertIn("not announced", eol_a.eol_text)
        eol_b = next(f for f in report.eol if f.cycle == "b")
        self.assertIn("unknown", eol_b.eol_text)

    def test_validation_no_supported_cycles(self):
        product = [
            {
                "cycle": "old",
                "releaseDate": "2000-01-01",
                "eol": "2005-01-01",
                "lts": True,
            }
        ]
        catalog = {"ubuntu": entry(["old"])}
        with self.assertRaises(cu.EvaluationError):
            cu.evaluate(catalog, {"ubuntu": product}, TODAY)

    def test_validation_enabled_cycle_missing_upstream(self):
        catalog = {"ubuntu": entry(["77.04"])}  # not in UBUNTU
        with self.assertRaises(cu.EvaluationError):
            cu.evaluate(catalog, {"ubuntu": UBUNTU}, TODAY)


class ParseEolTest(unittest.TestCase):
    def test_date(self):
        self.assertEqual(
            cu.parse_eol("2027-04-01"), ("date", datetime.date(2027, 4, 1))
        )

    def test_not_announced(self):
        self.assertEqual(cu.parse_eol(False), ("not_announced", None))

    def test_already_eol(self):
        self.assertEqual(cu.parse_eol(True), ("already_eol", None))


class RenderTest(unittest.TestCase):
    def test_both_sections(self):
        report = cu.Report(
            new_majors=[cu.Finding("ubuntu", "26.04", "2026-04-23", "2031-04-30")],
            eol=[cu.Finding("opensuse", "15.6", "2024-06-12", "2026-04-30")],
        )
        md = cu.render_markdown(report)
        self.assertIn("## New versions available", md)
        self.assertIn("## End-of-life images", md)
        self.assertIn("**ubuntu**: 26.04", md)
        self.assertIn("**opensuse**: 15.6", md)

    def test_empty(self):
        self.assertEqual(
            cu.render_markdown(cu.Report(new_majors=[], eol=[])).strip(), ""
        )


class ReadCatalogTest(unittest.TestCase):
    def _write_minimal(self, directory, name):
        with open(os.path.join(directory, f"{name}.yml"), "w") as fp:
            fp.write(
                "---\nimages:\n  - name: X\n    enable: true\n"
                "    shortname: x\n    meta:\n      os_version: '1'\n"
            )

    def test_missing_mapped_file_raises(self):
        # A mapped file absent is an anomaly, not "skip" — must raise so the run
        # cannot report clean and close the issue.
        d = tempfile.mkdtemp()
        try:
            self._write_minimal(d, "ubuntu")  # the other five are missing
            with self.assertRaises(cu.EvaluationError):
                cu.read_catalog(d)
        finally:
            shutil.rmtree(d)

    def test_all_present_returns_all(self):
        d = tempfile.mkdtemp()
        try:
            for name in cu.DISTROS:
                self._write_minimal(d, name)
            catalog = cu.read_catalog(d)
            self.assertEqual(set(catalog), set(cu.DISTROS))
            self.assertEqual(catalog["ubuntu"].enabled, {"1"})
        finally:
            shutil.rmtree(d)


from unittest import mock  # noqa: E402

import typer  # noqa: E402


class MainExitTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "report.md")
        self.status = os.path.join(self.dir, "status.txt")

    def tearDown(self):
        shutil.rmtree(self.dir)

    @staticmethod
    def _read(path):
        with open(path) as fp:
            return fp.read()

    def _run(self, catalog, **fetch_kw):
        # Mock read_catalog (tested on its own in ReadCatalogTest) so this
        # isolates the exit-code / sentinel plumbing. main() raises typer.Exit
        # (a RuntimeError subclass with .exit_code, NOT a SystemExit) when called
        # directly, bypassing the Typer runtime.
        with mock.patch.object(
            cu, "read_catalog", return_value=catalog
        ), mock.patch.object(cu, "fetch_product", **fetch_kw):
            try:
                cu.main(
                    images_dir=self.dir,
                    today="2026-06-01",
                    output=self.out,
                    status_file=self.status,
                    debug=False,
                )
                return 0
            except typer.Exit as e:
                return e.exit_code

    def test_findings_exit_1_and_sentinel(self):
        code = self._run({"ubuntu": entry(["22.04", "24.04"])}, return_value=UBUNTU)
        self.assertEqual(code, 1)
        self.assertEqual(self._read(self.status).strip(), "findings")
        self.assertIn("26.04", self._read(self.out))

    def test_clean_exit_0_and_sentinel(self):
        product = [
            {
                "cycle": "24.04",
                "releaseDate": "2024-04-25",
                "eol": "2029-04-25",
                "lts": True,
            },
        ]
        code = self._run({"ubuntu": entry(["24.04"])}, return_value=product)
        self.assertEqual(code, 0)
        self.assertEqual(self._read(self.status).strip(), "clean")

    def test_operational_failure_exit_2_no_sentinel(self):
        code = self._run({"ubuntu": entry(["24.04"])}, side_effect=RuntimeError("boom"))
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.status))


if __name__ == "__main__":
    unittest.main()
