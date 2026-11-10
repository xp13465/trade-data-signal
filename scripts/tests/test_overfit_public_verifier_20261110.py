"""#374 verifier compatibility: actual worker/functions, fake public transports only."""
import io
import socket
import os
import sys
import subprocess
import urllib.error
import urllib.request

import pytest

from scripts.tests.test_overfit_delivery_20261109 import load_functions, worker_fixture

REAL_SUBPROCESS_RUN = subprocess.run


def test_worker_403_uses_compatible_transport_without_changing_urls(tmp_path, monkeypatch, capsys):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    urls, calls = [], []
    def forbidden(request, timeout):
        urls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO())
    def curl(command, **kwargs):
        calls.append(command)
        name = command[-1].rsplit("/", 1)[1]
        return subprocess.CompletedProcess(command, 0, (data / name).read_bytes() + b"\n200", b"")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "run", curl)
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    assert ns["_delivery_worker"]() == 0
    assert len(urls) == len(calls) == 4
    assert [c[-1] for c in calls] == urls == [
        f"https://{host}/data/{name}"
        for host in ("ss.fx8.store", "ssd.fx8.store")
        for name in ("overfit_monitor.json", "overfit_monitor_ext.json")]
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}
    assert events[-1] == ("release", 12)
    assert "urllib HTTP403" in capsys.readouterr().err


@pytest.fixture(autouse=True)
def forbid_real_network_and_curl(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("real network prohibited"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("real curl prohibited"))


@pytest.mark.parametrize("failure", ["http503", "tls", "partial", "timeout", "missing",
                                      "short", "extra", "hash", "redirect", "no-status"])
def test_curl_negative_controls_preserve_76_and_source(tmp_path, monkeypatch, failure, capsys):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    seen = []
    def forbidden(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO())
    def curl(command, **kwargs):
        seen.append(command)
        body = (data / command[-1].rsplit("/", 1)[1]).read_bytes()
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "missing":
            raise FileNotFoundError("curl")
        rc, status = {"http503": (22, b"503"), "tls": (60, b"000"),
                      "partial": (18, b"200"), "redirect": (0, b"302")}.get(failure, (0, b"200"))
        body = body[:-1] if failure == "short" else body + b"x" if failure == "extra" else b"x" * len(body) if failure == "hash" else body
        return subprocess.CompletedProcess(command, rc, body + b"\n" + status if failure != "no-status" else body, b"do not disclose response/env")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "run", curl)
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    assert ns["_delivery_worker"]() == 76
    assert len(seen) == 1
    assert events[-1] == ("release", 12)
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}
    stderr = capsys.readouterr().err
    assert "urllib HTTP403" in stderr and "R2_PUBLIC_UNCONFIRMED" in stderr
    assert "do not disclose" not in stderr
    if failure in ("tls", "partial", "http503"):
        assert {"tls": "rc=60", "partial": "rc=18", "http503": "rc=22"}[failure] in stderr


@pytest.mark.parametrize("failure", ["404", "503", "tls", "timeout", "short", "hash"])
def test_non403_or_invalid_urllib_is_not_retried(tmp_path, monkeypatch, failure):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    def read(req, timeout):
        if failure.isdigit():
            raise urllib.error.HTTPError(req.full_url, int(failure), "failure", {}, io.BytesIO())
        if failure == "tls":
            raise urllib.error.URLError("certificate verification failed")
        if failure == "timeout":
            raise TimeoutError("timed out")
        body = (data / req.full_url.rsplit("/", 1)[1]).read_bytes()
        return io.BytesIO(body[:-1] if failure == "short" else b"x" * len(body))
    monkeypatch.setattr(urllib.request, "urlopen", read)
    assert ns["_delivery_worker"]() == 76
    assert events[-1] == ("release", 12)


def test_curl_arguments_tls_bounded_and_no_user_agent_override(monkeypatch):
    ns = load_functions()
    url = "https://ss.fx8.store/data/overfit_monitor.json"
    ticks = iter([10, 10, 12])
    monkeypatch.setattr(ns["time"], "monotonic", lambda: next(ticks, 12))
    def forbidden(req, timeout):
        assert req.full_url == url and req.get_header("User-agent") is None
        assert timeout == 5
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO())
    def curl(command, **kw):
        assert command[:2] == ["curl", "--disable"]
        assert command[-2:] == ["--url", url]
        assert command[command.index("--max-time") + 1] == "3"
        assert command[command.index("--connect-timeout") + 1] == "3"
        assert command[command.index("--max-filesize") + 1] == "4"
        assert command[command.index("--proto") + 1] == "=https"
        assert command[command.index("--cacert") + 1]
        assert command[command.index("--header") + 1] == "Cache-Control: no-cache"
        assert not set(command) & {"-k", "--insecure", "-A", "--user-agent", "-L", "--location", "--retry"}
        assert kw["timeout"] == 3 and kw["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, b"data\n200", b"")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "run", curl)
    assert ns["_read_overfit_public"](url, 4, timeout=5) == b"data"


@pytest.mark.parametrize("timeout", [0, -1])
def test_exhausted_budget_makes_no_http_call(monkeypatch, timeout):
    ns = load_functions()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("budget already exhausted"))
    with pytest.raises(TimeoutError):
        ns["_read_overfit_public"]("https://ss.fx8.store/data/overfit_monitor.json", 4, timeout=timeout)


def test_pure_pair_verifier_uses_remaining_work_for_all_four_requests():
    ns = load_functions()
    payloads, seen = [b"main", b"ext"], []
    def read(url, size, timeout):
        seen.append((url, size, timeout))
        return payloads[len(seen) % 2 - 1]
    ns["_read_overfit_public"] = read
    budgets = iter([50, 29, 2, 0.1])
    assert ns["_verify_overfit_public_pair"](payloads, remaining_work=lambda: next(budgets)) is None
    assert [x[2] for x in seen] == [30, 29, 2, 0.1]


def test_invalid_pair_does_not_silently_zip_away_a_file():
    ns = load_functions()
    ns["_read_overfit_public"] = lambda *a: pytest.fail("invalid pair must not GET")
    with pytest.raises(ValueError, match="pair"):
        ns["_verify_overfit_public_pair"]([b"main"])


@pytest.mark.parametrize("mode", ["ok", "tls-fail", "timeout"])
def test_real_subprocess_with_fake_curl_and_timeout_reaping(tmp_path, monkeypatch, mode):
    ns = load_functions()
    url = "https://ss.fx8.store/data/overfit_monitor.json"
    def forbidden(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO())
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    pidfile = tmp_path / "curl.pid"
    fake = tmp_path / "curl"
    program = f"#!{sys.executable}\nimport os,sys,time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
    program += "time.sleep(5)\n" if mode == "timeout" else "raise SystemExit(60)\n" if mode == "tls-fail" else "sys.stdout.buffer.write(b'data\\n200')\n"
    fake.write_text(program)
    fake.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    def run(command, **kwargs):
        assert command[0] == "curl"
        return REAL_SUBPROCESS_RUN(command, **kwargs)
    monkeypatch.setattr(subprocess, "run", run)
    if mode == "ok":
        assert ns["_read_overfit_public"](url, 4, timeout=1) == b"data"
    else:
        with pytest.raises(RuntimeError, match="TimeoutExpired" if mode == "timeout" else "rc=60"):
            ns["_read_overfit_public"](url, 4, timeout=1.5 if mode == "timeout" else 2)
    assert pidfile.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
