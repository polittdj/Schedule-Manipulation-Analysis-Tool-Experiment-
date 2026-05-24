"""Native MS Project ``.mpp`` importer via MPXJ as a SUBPROCESS (never in-process JPype).

MPXJ (a Java library) reads many native schedule formats (``.mpp``, ``.mpx``,
``.xer``, MSPDI XML, ...). We invoke it as an EXTERNAL process to convert the
input file to MSPDI XML, then reuse the proven pure-Python MSPDI importer
(:func:`schedule_forensics.importers.msp_xml.parse_msp_xml`). The JVM stays fully
out-of-process and killable -- Commandment 1: **NEVER in-process JPype** (the top
historical build-failure cause).

MPXJ is an OPTIONAL, user-provided runtime dependency (like the Windows COM
enhancement) -- discovered at runtime, never bundled, so the repo and CI stay
lean. Configure it via ONE of:

  * ``SF_MPXJ_CMD`` -- a command template; the ``{input}`` and ``{output}`` tokens
    are replaced with the file paths, e.g.::

        SF_MPXJ_CMD="java -cp /opt/mpxj/lib/* org.mpxj.cli.MpxjConvert {input} {output}"

    (Java expands a ``-cp dir/*`` classpath wildcard itself; no shell is used.)
  * ``SF_MPXJ_JAR`` -- a runnable jar; we invoke ``java -jar <jar> {input} {output}``.

If neither is set (or ``java`` is missing, or the conversion fails/times out), the
importer raises :class:`ImporterError` -- it NEVER silently returns nothing
(LAW 2, fail closed). Because a true binary ``.mpp`` cannot be authored on Linux,
the ``.mpp`` path itself is validated on a machine with MPXJ + a real ``.mpp``;
here the subprocess plumbing is tested hermetically with a stub converter.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from schedule_forensics.importers.msp_xml import ImporterError as MspImporterError
from schedule_forensics.importers.msp_xml import parse_msp_xml
from schedule_forensics.schemas import Calendar, Schedule

_CMD_ENV = "SF_MPXJ_CMD"
_JAR_ENV = "SF_MPXJ_JAR"
_HOME_ENV = "SF_MPXJ_HOME"  # dir with classes/ + lib/ produced by tools/mpxj/setup.sh
_DEFAULT_TIMEOUT_S = 120.0

# Message shown when no MPXJ runner is configured (kept user-actionable).
_NOT_CONFIGURED = (
    f"native .mpp parsing needs MPXJ (Java). Run tools/mpxj/setup.sh -- it builds into "
    f"the default tools/mpxj/ location, which this importer auto-discovers (no env var "
    f"needed). For a custom install set {_HOME_ENV}, {_CMD_ENV} (a command template with "
    f"{{input}}/{{output}}), or {_JAR_ENV} (a runnable MPXJ jar). See docs/MPXJ.md."
)


class ImporterError(ValueError):
    """Raised when a native file cannot be imported via the MPXJ subprocess."""


def _default_mpxj_home() -> str | None:
    """The conventional in-repo MPXJ install (``tools/mpxj``) if it is built, else None.

    Zero-config discovery: once ``tools/mpxj/setup.sh`` has run, the web UI, the CLI,
    and tests read native ``.mpp`` with NO ``SF_MPXJ_*`` env var set -- which is what
    makes ``.mpp`` parsing work out of the box across sessions and across processes
    (an env var exported in a setup hook does not reliably reach the web server's
    process). Returned only when BOTH the compiled converter and at least one
    dependency jar are present; otherwise ``None`` so the importer still fails closed.
    """
    # mpp_mpxj.py -> importers -> schedule_forensics -> src -> <repo root>
    home = Path(__file__).resolve().parents[3] / "tools" / "mpxj"
    if (home / "classes" / "MpxjToMspdi.class").is_file() and any(home.glob("lib/*.jar")):
        return str(home)
    return None


def mpxj_configured(environ: Mapping[str, str] | None = None) -> bool:
    """True iff MPXJ is usable: a ``SF_MPXJ_*`` env runner OR a built default install."""
    env = os.environ if environ is None else environ
    if env.get(_HOME_ENV) or env.get(_CMD_ENV) or env.get(_JAR_ENV):
        return True
    return _default_mpxj_home() is not None


def _build_command(input_path: str, output_path: str, env: Mapping[str, str]) -> list[str]:
    """Build the converter argv from the configured env (no shell; argv list).

    Resolution order: SF_MPXJ_CMD (explicit template) > SF_MPXJ_JAR (runnable jar) >
    SF_MPXJ_HOME (the classes/+lib/ dir from setup.sh) > the auto-discovered default
    in-repo install (``tools/mpxj`` if built). Java expands the ``lib/*`` classpath
    wildcard itself.
    """
    cmd_template = env.get(_CMD_ENV)
    if cmd_template:
        tokens = shlex.split(cmd_template)
        has_input = any("{input}" in t for t in tokens)
        has_output = any("{output}" in t for t in tokens)
        if not (has_input and has_output):
            raise ImporterError(
                f"{_CMD_ENV} must contain the {{input}} and {{output}} placeholders"
            )
        return [t.replace("{input}", input_path).replace("{output}", output_path) for t in tokens]
    jar = env.get(_JAR_ENV)
    if jar:
        return ["java", "-jar", jar, input_path, output_path]
    # Explicit SF_MPXJ_HOME wins; otherwise fall back to a built default tools/mpxj.
    home = env.get(_HOME_ENV) or _default_mpxj_home()
    if home:
        classpath = os.path.join(home, "classes") + os.pathsep + os.path.join(home, "lib", "*")
        return ["java", "-cp", classpath, "MpxjToMspdi", input_path, output_path]
    raise ImporterError(f"MPXJ is not configured: {_NOT_CONFIGURED}")


def parse_mpp(
    path: str | os.PathLike[str],
    *,
    calendar: Calendar | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    environ: Mapping[str, str] | None = None,
) -> Schedule:
    """Import a native ``.mpp`` (or any MPXJ-readable file) into a :class:`Schedule`.

    Runs the configured MPXJ converter as an out-of-process, killable subprocess
    (terminated on ``timeout_s``) to produce MSPDI XML in a temp dir, then parses
    that with the proven pure-Python MSPDI importer. Raises :class:`ImporterError`
    if MPXJ is unconfigured/unavailable or the conversion fails (fail closed).
    """
    env = os.environ if environ is None else environ
    src = Path(path)
    if not src.is_file():
        raise ImporterError(f"input file does not exist: {src}")

    with tempfile.TemporaryDirectory(prefix="sf_mpxj_") as tmp:
        out_path = os.path.join(tmp, "converted.xml")
        cmd = _build_command(str(src), out_path, env)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ImporterError(
                f"could not launch the MPXJ converter ({cmd[0]!r} not found). Is Java installed "
                f"and is {_CMD_ENV}/{_JAR_ENV} correct?"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ImporterError(
                f"MPXJ conversion timed out after {timeout_s}s and was terminated"
            ) from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise ImporterError(
                f"MPXJ conversion failed (exit {result.returncode}): {stderr or '(no stderr)'}"
            )
        if not os.path.isfile(out_path):
            raise ImporterError("MPXJ conversion produced no output file")

        try:
            return parse_msp_xml(out_path, calendar=calendar)
        except MspImporterError as exc:
            raise ImporterError(f"MPXJ output is not valid MSPDI: {exc}") from exc
