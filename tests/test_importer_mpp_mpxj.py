"""MPXJ-subprocess importer tests.

The subprocess->parse pipeline is verified HERMETICALLY with a stub "converter"
(a tiny Python script that writes a known MSPDI document to the output path), so
the importer's logic is fully exercised WITHOUT the 30 MB MPXJ/Java toolchain.
A real-MPXJ integration test runs only when SF_MPXJ_INTEGRATION is set (graceful
degradation, like the COM importer). Fail-closed paths (unconfigured, missing
java, non-zero exit, timeout, bad output) are all asserted to raise ImporterError
-- never a silent empty result (LAW 2).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from schedule_forensics.importers.mpp_mpxj import (
    ImporterError,
    _build_command,
    mpxj_configured,
    parse_mpp,
)

_FIXTURES = Path(__file__).parent / "fixtures"
MSPDI_FIXTURE = _FIXTURES / "msp_xml" / "simple_network.xml"


def _stub_cmd(tmp_path: Path, body: str) -> str:
    """Write a Python stub 'converter' and return an SF_MPXJ_CMD template invoking it."""
    stub = tmp_path / "stub_converter.py"
    stub.write_text(body)
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(stub))} {{input}} {{output}}"


def _dummy_mpp(tmp_path: Path) -> Path:
    p = tmp_path / "schedule.mpp"
    p.write_bytes(b"\xd0\xcf\x11\xe0not-a-real-mpp")  # content is irrelevant to the stub
    return p


# ── command construction ──────────────────────────────────────────────────────


def test_build_command_from_cmd_template() -> None:
    cmd = _build_command("IN", "OUT", {"SF_MPXJ_CMD": "java -cp x.jar Main {input} {output}"})
    assert cmd == ["java", "-cp", "x.jar", "Main", "IN", "OUT"]


def test_build_command_from_jar() -> None:
    cmd = _build_command("IN", "OUT", {"SF_MPXJ_JAR": "/opt/mpxj.jar"})
    assert cmd == ["java", "-jar", "/opt/mpxj.jar", "IN", "OUT"]


def test_build_command_from_home() -> None:
    cmd = _build_command("IN", "OUT", {"SF_MPXJ_HOME": "/opt/mpxj"})
    assert cmd[:2] == ["java", "-cp"]
    assert "/opt/mpxj/classes" in cmd[2] and "/opt/mpxj/lib/*" in cmd[2]
    assert cmd[3:] == ["MpxjToMspdi", "IN", "OUT"]


def test_build_command_template_missing_tokens_raises() -> None:
    with pytest.raises(ImporterError, match="placeholders"):
        _build_command("IN", "OUT", {"SF_MPXJ_CMD": "java -jar x.jar"})


def test_mpxj_configured_reflects_env() -> None:
    assert mpxj_configured({"SF_MPXJ_JAR": "x.jar"}) is True
    assert mpxj_configured({"SF_MPXJ_CMD": "java {input} {output}"}) is True
    assert mpxj_configured({"SF_MPXJ_HOME": "/opt/mpxj"}) is True
    assert mpxj_configured({}) is False


# ── hermetic end-to-end via a stub converter ──────────────────────────────────


def test_stub_converter_roundtrips_to_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stub mimics MPXJ: ignore the input, write a known MSPDI doc to the output path.
    body = f"import shutil, sys\nshutil.copyfile({str(MSPDI_FIXTURE)!r}, sys.argv[2])\n"
    monkeypatch.setenv("SF_MPXJ_CMD", _stub_cmd(tmp_path, body))
    schedule = parse_mpp(_dummy_mpp(tmp_path))
    # The MSPDI fixture network flows through the subprocess + the real MSPDI parser.
    assert {t.unique_id for t in schedule.tasks} == {1, 2, 3, 4}
    assert schedule.task_by_id(1).duration_minutes == 960


def test_unconfigured_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SF_MPXJ_CMD", raising=False)
    monkeypatch.delenv("SF_MPXJ_JAR", raising=False)
    with pytest.raises(ImporterError, match="not configured"):
        parse_mpp(_dummy_mpp(tmp_path))


def test_missing_input_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SF_MPXJ_CMD", "java {input} {output}")
    with pytest.raises(ImporterError, match="does not exist"):
        parse_mpp("/no/such/file.mpp")


def test_converter_not_found_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SF_MPXJ_CMD", "/nonexistent/java-binary {input} {output}")
    with pytest.raises(ImporterError, match="not found"):
        parse_mpp(_dummy_mpp(tmp_path))


def test_nonzero_exit_raises_with_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = "import sys\nsys.stderr.write('boom from converter')\nsys.exit(3)\n"
    monkeypatch.setenv("SF_MPXJ_CMD", _stub_cmd(tmp_path, body))
    with pytest.raises(ImporterError, match="boom from converter"):
        parse_mpp(_dummy_mpp(tmp_path))


def test_empty_output_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Converter exits 0 but writes nothing to the output path.
    body = "import sys\nsys.exit(0)\n"
    monkeypatch.setenv("SF_MPXJ_CMD", _stub_cmd(tmp_path, body))
    with pytest.raises(ImporterError, match="no output file"):
        parse_mpp(_dummy_mpp(tmp_path))


def test_timeout_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SF_MPXJ_CMD", "java {input} {output}")

    def _raise_timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="java", timeout=1.0)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    with pytest.raises(ImporterError, match="timed out"):
        parse_mpp(_dummy_mpp(tmp_path), timeout_s=1.0)


def test_bad_converter_output_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Converter writes non-MSPDI garbage -> the MSPDI parser rejects it (fail closed).
    body = "import sys\nopen(sys.argv[2], 'w').write('<not-mspdi/>')\n"
    monkeypatch.setenv("SF_MPXJ_CMD", _stub_cmd(tmp_path, body))
    with pytest.raises(ImporterError):
        parse_mpp(_dummy_mpp(tmp_path))


# ── real MPXJ integration (opt-in; skips unless a real converter is wired) ────


@pytest.mark.skipif(
    not os.environ.get("SF_MPXJ_INTEGRATION"),
    reason="set SF_MPXJ_INTEGRATION=1 (with SF_MPXJ_CMD/JAR) to run against real MPXJ",
)
def test_real_mpxj_reads_a_fixture() -> None:
    # When real MPXJ is wired, it reads a real schedule file and writes MSPDI that
    # our parser recovers. MSPDI is used as the input because MPXJ's reader sniffs
    # the format and accepts it cleanly on any platform (no binary .mpp needed).
    schedule = parse_mpp(MSPDI_FIXTURE)
    assert {t.unique_id for t in schedule.tasks} == {1, 2, 3, 4}
    assert schedule.task_by_id(1).duration_minutes == 960  # fidelity through the real pipeline
    assert schedule.task_by_id(4).is_milestone is True
