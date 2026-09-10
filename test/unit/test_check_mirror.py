# SPDX-License-Identifier: Apache-2.0

import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

import requests
import typer
from urllib3.exceptions import ProtocolError

import contrib.check_mirror as cm

CATALOG = """\
---
images:
  - name: Ubuntu 24.04
    shortname: ubuntu-24.04
    versions:
      - version: '20260108'
        url: https://upstream.test/ubuntu-24.04.img
        mirror_url: https://object.test/osism/openstack-images/ubuntu-24.04/a.qcow2
  - name: AlmaLinux 10
    shortname: almalinux-10
    versions:
      - version: '20260526'
        url: https://upstream.test/almalinux-10.qcow2
        mirror_url: https://object.test/osism/openstack-images/almalinux-10/b.qcow2
"""

MIRROR_A = "https://object.test/osism/openstack-images/ubuntu-24.04/a.qcow2"
MIRROR_B = "https://object.test/osism/openstack-images/almalinux-10/b.qcow2"
UPSTREAM_A = "https://upstream.test/ubuntu-24.04.img"
UPSTREAM_B = "https://upstream.test/almalinux-10.qcow2"


def _response(status, chain=(), body=b"\x00"):
    """A real requests.Response, optionally behind a redirect history.

    Defaults to a nonempty body: fetchable() now reads a byte from a FETCHED
    response, and redirect hops are never read so their bodies stay empty.
    """
    response = requests.Response()
    response.status_code = status
    response.raw = io.BytesIO(body)
    for code in chain:
        hop = requests.Response()
        hop.status_code = code
        hop.raw = io.BytesIO(b"")
        response.history.append(hop)
    return response


def _get(statuses):
    """Stand in for requests.get, answering per URL.

    A value is either a status, or a (final status, redirect chain before it)
    tuple, optionally followed by a body (default: a nonempty stand-in byte).
    A url the test did not list raises KeyError, so every probe a test expects
    has to be spelled out.
    """

    def get(url, **kwargs):
        entry = statuses[url]
        if isinstance(entry, tuple):
            status, chain = entry[0], entry[1]
            body = entry[2] if len(entry) > 2 else b"\x00"
        else:
            status, chain, body = entry, (), b"\x00"
        return _response(status, chain, body)

    return get


def _head(statuses):
    """Stand in for requests.head, answering per URL."""

    def head(url, **kwargs):
        return _response(statuses[url])

    return head


class _BrokenBody:
    """A body whose transfer dies partway through.

    Modelled on test_mirror.py's _BrokenStream: requests uses raw.stream()
    when present and translates the urllib3 error it raises into
    ChunkedEncodingError.
    """

    def stream(self, chunk_size, decode_content=True):
        raise ProtocolError("connection broken: incomplete read")

    def read(self, size=-1):
        raise ProtocolError("connection broken: incomplete read")

    def close(self):
        pass


class CheckMirrorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "images.yml"), "w") as fp:
            fp.write(CATALOG)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _evaluate(self, head, get):
        with mock.patch.object(cm.requests, "head", _head(head)):
            with mock.patch.object(cm.requests, "get", _get(get)):
                return cm.evaluate(self.dir)

    def test_healthy_objects_are_clean(self):
        # The real shape, verified against the store: HEAD answers 200 and the
        # ranged GET answers 206. Reading the GET's status as the manager's
        # gate would reject exactly this, the case that is fine.
        report = self._evaluate(
            head={MIRROR_A: 200, MIRROR_B: 200},
            get={MIRROR_A: 206, MIRROR_B: 206},
        )

        self.assertTrue(report.is_empty())

    def test_plain_200_from_both_probes_is_clean(self):
        report = self._evaluate(
            head={MIRROR_A: 200, MIRROR_B: 200},
            get={MIRROR_A: 200, MIRROR_B: 200},
        )

        self.assertTrue(report.is_empty())

    def test_redirect_that_ends_in_bytes_is_retrievable(self):
        report = self._evaluate(
            head={MIRROR_A: 302, MIRROR_B: 200},
            get={MIRROR_A: (200, (302,)), MIRROR_B: 206},
        )

        self.assertTrue(report.is_empty())

    def test_redirect_to_a_dead_target_is_not_retrievable(self):
        # The manager's gate sees only the first response, so a 302 passes it.
        # The bytes never arrive, so this is still a gap.
        report = self._evaluate(
            head={MIRROR_A: 302, MIRROR_B: 200},
            get={MIRROR_A: (404, (302,)), UPSTREAM_A: 200, MIRROR_B: 206},
        )

        self.assertEqual([f.shortname for f in report.pending], ["ubuntu-24.04"])
        self.assertIn("GET 302 -> 404", report.pending[0].mirror_status)

    def test_redirect_the_manager_refuses_is_not_retrievable(self):
        # Bytes arrive, but main.py:991 accepts only 200 or 302 from its own
        # HEAD, so a 301 fails the import while the bytes look fine.
        report = self._evaluate(
            head={MIRROR_A: 301, MIRROR_B: 200},
            get={MIRROR_A: 200, UPSTREAM_A: 200, MIRROR_B: 206},
        )

        self.assertEqual([f.shortname for f in report.pending], ["ubuntu-24.04"])
        self.assertIn("the manager refuses a 301", report.pending[0].mirror_status)

    def test_absent_object_with_live_upstream_is_pending(self):
        report = self._evaluate(
            head={MIRROR_A: 403, MIRROR_B: 200},
            get={MIRROR_A: 403, UPSTREAM_A: 200, MIRROR_B: 206},
        )

        self.assertEqual([f.shortname for f in report.pending], ["ubuntu-24.04"])
        self.assertEqual(report.unmirrorable, [])

    def test_absent_object_with_dead_upstream_is_unmirrorable(self):
        report = self._evaluate(
            head={MIRROR_A: 200, MIRROR_B: 403},
            get={MIRROR_A: 206, MIRROR_B: 403, UPSTREAM_B: 404},
        )

        self.assertEqual([f.shortname for f in report.unmirrorable], ["almalinux-10"])
        self.assertEqual(report.pending, [])

    def test_upstream_redirect_still_counts_as_reachable(self):
        # mirror_version() in contrib/mirror.py downloads upstream with
        # allow_redirects=True, so a 301 chain upstream is not a problem and
        # must classify as pending, not unmirrorable. gardenlinux redirects.
        report = self._evaluate(
            head={MIRROR_A: 403, MIRROR_B: 200},
            get={MIRROR_A: 403, UPSTREAM_A: (200, (301,)), MIRROR_B: 206},
        )

        self.assertEqual([f.shortname for f in report.pending], ["ubuntu-24.04"])
        self.assertEqual(report.unmirrorable, [])

    def test_403_is_reported_as_a_status_not_as_absence(self):
        # Hetzner answers 403 for a key that does not exist -- and so does an
        # object that exists and lost its public read permission. The report
        # may not claim either, in the fields or in the prose.
        report = self._evaluate(
            head={MIRROR_A: 403, MIRROR_B: 200},
            get={MIRROR_A: 403, UPSTREAM_A: 200, MIRROR_B: 206},
        )

        self.assertEqual(report.pending[0].mirror_status, "HEAD 403, GET 403")

        text = cm.render(report).lower()
        for claim in ("missing", "absent", "no copy"):
            self.assertNotIn(claim, text)
        self.assertIn("not retrievable", text)

    def test_success_status_with_empty_body_is_not_retrievable(self):
        # A server can answer a healthy status and then send nothing. That is
        # not retrievable, and the report must say why, not just repeat the
        # status a healthy object would also show.
        for status in (200, 206):
            with self.subTest(status=status):
                response = _response(status, body=b"")
                with mock.patch.object(cm.requests, "get", return_value=response):
                    arrived, text = cm.fetchable(MIRROR_A)

                self.assertFalse(arrived)
                self.assertIn("empty body", text)
                self.assertIn(str(status), text)

    def test_empty_mirror_body_with_live_upstream_is_pending(self):
        # The classification logic must still route an empty-body mirror as
        # pending, not unmirrorable, when upstream still has bytes.
        report = self._evaluate(
            head={MIRROR_A: 200, MIRROR_B: 200},
            get={MIRROR_A: (206, (), b""), UPSTREAM_A: 200, MIRROR_B: 206},
        )

        self.assertEqual([f.shortname for f in report.pending], ["ubuntu-24.04"])
        self.assertEqual(report.unmirrorable, [])
        self.assertIn("empty body", report.pending[0].mirror_status)

    def test_transport_failure_is_operational(self):
        def head(url, **kwargs):
            raise requests.ConnectionError("name resolution failed")

        with mock.patch.object(cm.time, "sleep"):
            with mock.patch.object(cm.requests, "head", head):
                with self.assertRaises(cm.OperationalError):
                    cm.evaluate(self.dir)


class RetryTest(unittest.TestCase):
    """A single transport hiccup must not fail a probe outright."""

    def test_failure_then_success_returns_the_eventual_verdict(self):
        # The first GET resets, the second answers 206 -- the probe must
        # return the successful verdict, not raise.
        attempts = []

        def get(url, **kwargs):
            attempts.append(url)
            if len(attempts) < 2:
                raise requests.ConnectionError("connection reset")
            return _response(206)

        with mock.patch.object(cm.time, "sleep") as sleep:
            with mock.patch.object(cm.requests, "get", get):
                arrived, status = cm.fetchable(MIRROR_A)

        self.assertTrue(arrived)
        self.assertEqual(status, "206")
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once()

    def test_every_attempt_failing_raises_operational_error(self):
        def head(url, **kwargs):
            raise requests.ConnectionError("connection reset")

        with mock.patch.object(cm.time, "sleep") as sleep:
            with mock.patch.object(cm.requests, "head", head):
                with self.assertRaises(cm.OperationalError):
                    cm.accepted_by_manager(MIRROR_A)

        # Slept between attempts, but not after the last one.
        self.assertEqual(sleep.call_count, cm.RETRY_ATTEMPTS - 1)

    def test_an_http_status_is_never_retried(self):
        # A verdict -- even an unwelcome one -- must not trigger a retry.
        calls = []

        def head(url, **kwargs):
            calls.append(url)
            return _response(403)

        with mock.patch.object(cm.time, "sleep") as sleep:
            with mock.patch.object(cm.requests, "head", head):
                accepted, status = cm.accepted_by_manager(MIRROR_A)

        self.assertFalse(accepted)
        self.assertEqual(status, "403")
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_non_fetched_status_does_not_read_the_body(self):
        # A 403's error payload is irrelevant and must not be read.
        response = _response(403)
        response.raw = _BrokenBody()

        with mock.patch.object(cm.requests, "get", return_value=response):
            arrived, status = cm.fetchable(MIRROR_A)

        self.assertFalse(arrived)
        self.assertEqual(status, "403")

    def test_body_failure_every_attempt_raises_operational_error(self):
        # The byte read has to sit inside probe()'s retry scope: a body that
        # dies mid-transfer on every attempt must end up OperationalError,
        # exactly like a failure while reading the headers.
        def get(url, **kwargs):
            response = _response(206)
            response.raw = _BrokenBody()
            return response

        with mock.patch.object(cm.time, "sleep") as sleep:
            with mock.patch.object(cm.requests, "get", get):
                with self.assertRaises(cm.OperationalError):
                    cm.fetchable(MIRROR_A)

        self.assertEqual(sleep.call_count, cm.RETRY_ATTEMPTS - 1)

    def test_body_failure_then_success_returns_the_eventual_verdict(self):
        # The first GET's body dies mid-transfer, the second delivers a byte
        # -- this is the test that proves the read sits inside the retry
        # scope, not just the headers.
        attempts = []

        def get(url, **kwargs):
            attempts.append(url)
            response = _response(206)
            if len(attempts) < 2:
                response.raw = _BrokenBody()
            return response

        with mock.patch.object(cm.time, "sleep") as sleep:
            with mock.patch.object(cm.requests, "get", get):
                arrived, status = cm.fetchable(MIRROR_A)

        self.assertTrue(arrived)
        self.assertEqual(status, "206")
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once()


class ExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "images.yml"), "w") as fp:
            fp.write(CATALOG)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _run(self, head, get):
        # typer.Exit is a RuntimeError subclass carrying .exit_code, not SystemExit.
        with mock.patch.object(cm.requests, "head", _head(head)):
            with mock.patch.object(cm.requests, "get", _get(get)):
                with self.assertRaises(typer.Exit) as caught:
                    cm.main(images=self.dir, debug=False)
        return caught.exception.exit_code

    def test_clean_exits_zero(self):
        self.assertEqual(
            self._run(
                head={MIRROR_A: 200, MIRROR_B: 200},
                get={MIRROR_A: 206, MIRROR_B: 206},
            ),
            0,
        )

    def test_pending_only_exits_three(self):
        self.assertEqual(
            self._run(
                head={MIRROR_A: 403, MIRROR_B: 200},
                get={MIRROR_A: 403, UPSTREAM_A: 200, MIRROR_B: 206},
            ),
            3,
        )

    def test_unmirrorable_exits_one(self):
        self.assertEqual(
            self._run(
                head={MIRROR_A: 403, MIRROR_B: 200},
                get={MIRROR_A: 403, UPSTREAM_A: 404, MIRROR_B: 206},
            ),
            1,
        )

    def test_unmirrorable_wins_over_pending(self):
        # A run with both must fail everywhere, not be tolerated as pending.
        self.assertEqual(
            self._run(
                head={MIRROR_A: 403, MIRROR_B: 403},
                get={
                    MIRROR_A: 403,
                    UPSTREAM_A: 200,
                    MIRROR_B: 403,
                    UPSTREAM_B: 404,
                },
            ),
            1,
        )

    def test_transport_failure_exits_two(self):
        def head(url, **kwargs):
            raise requests.ConnectionError("name resolution failed")

        with mock.patch.object(cm.time, "sleep"):
            with mock.patch.object(cm.requests, "head", head):
                with self.assertRaises(typer.Exit) as caught:
                    cm.main(images=self.dir, debug=False)

        self.assertEqual(caught.exception.exit_code, 2)

    def test_body_failure_every_attempt_exits_two(self):
        def get(url, **kwargs):
            response = _response(206)
            response.raw = _BrokenBody()
            return response

        with mock.patch.object(cm.time, "sleep"):
            with mock.patch.object(
                cm.requests, "head", _head({MIRROR_A: 200, MIRROR_B: 200})
            ):
                with mock.patch.object(cm.requests, "get", get):
                    with self.assertRaises(typer.Exit) as caught:
                        cm.main(images=self.dir, debug=False)

        self.assertEqual(caught.exception.exit_code, 2)


class RenderTest(unittest.TestCase):
    def test_empty_report_renders_nothing(self):
        self.assertEqual(cm.render(cm.Report()), "")

    def test_both_classes_are_named_in_the_inventory(self):
        report = cm.Report(
            pending=[
                cm.Finding(
                    "Ubuntu 26.04",
                    "ubuntu-26.04",
                    "20260717",
                    MIRROR_A,
                    "HEAD 403, GET 403",
                    "200",
                )
            ],
            unmirrorable=[
                cm.Finding(
                    "CentOS Stream 10",
                    "centos-stream-10",
                    "20260902",
                    MIRROR_B,
                    "HEAD 403, GET 403",
                    "404",
                )
            ],
        )

        text = cm.render(report)

        self.assertIn("Ubuntu 26.04 ubuntu-26.04 20260717", text)
        self.assertIn("CentOS Stream 10 centos-stream-10 20260902", text)
        self.assertIn("Pending mirror", text)
        self.assertIn("Unmirrorable", text)

    def test_headings_describe_observations_not_absence(self):
        report = cm.Report(
            pending=[
                cm.Finding(
                    "Ubuntu 26.04",
                    "ubuntu-26.04",
                    "20260717",
                    MIRROR_A,
                    "HEAD 403, GET 403",
                    "200",
                )
            ],
            unmirrorable=[
                cm.Finding(
                    "CentOS Stream 10",
                    "centos-stream-10",
                    "20260902",
                    MIRROR_B,
                    "HEAD 403, GET 403",
                    "404",
                )
            ],
        )

        text = cm.render(report).lower()

        self.assertIn("mirror not retrievable, upstream retrievable", text)
        self.assertIn("upstream not retrievable", text)
        for claim in ("missing", "absent", "no copy"):
            self.assertNotIn(claim, text)


if __name__ == "__main__":
    unittest.main()
