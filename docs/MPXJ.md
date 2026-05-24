# Native `.mpp` ingestion via MPXJ (optional, user-provided)

`importers/mpp_mpxj.py` reads native MS Project `.mpp` (and `.mpx`, `.xer`,
MSPDI) files by invoking **MPXJ** (a Java library) as an **out-of-process,
killable subprocess** that converts the file to MSPDI XML; the proven pure-Python
`parse_msp_xml` then reads that. The JVM never runs inside the Python process
(Commandment 1: **never in-process JPype**).

MPXJ is an **optional runtime dependency** — like the Windows COM path, it is
discovered at runtime and is **not bundled** (keeps the repo and CI lean). Once it
is built into its default location (`tools/mpxj/`), the importer **auto-discovers
it with no environment variable** — so the web UI and CLI read `.mpp` out of the
box. If it is not built (and no `SF_MPXJ_*` override is set), `parse_mpp` raises
`ImporterError` (fail closed); the rest of the tool is unaffected.

> **Automated setup.** A `SessionStart` hook (`.claude/hooks/session-start.sh`)
> builds MPXJ on the first Claude Code on the web session, and the one-click
> launchers (`launch/`) build it on their first run. Both are idempotent, so in
> practice `.mpp` parsing "just works" without any manual step. The manual
> instructions below are for other environments or troubleshooting.

> **LAW 1:** MPXJ runs locally and does no network I/O. The conversion writes a
> temp MSPDI file that is deleted immediately after parsing; no schedule data
> leaves the machine.

## Quick setup (recommended)

**macOS / Linux:**

```sh
bash tools/mpxj/setup.sh                  # needs Java (JDK >= 17) + Maven
# That's it — the importer auto-discovers tools/mpxj. Setting SF_MPXJ_HOME is only
# needed if you install MPXJ somewhere else:
# export SF_MPXJ_HOME="$PWD/tools/mpxj"
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File tools\mpxj\setup.ps1   # needs Java (JDK >= 17) + Maven
$env:SF_MPXJ_HOME = "$PWD\tools\mpxj"      # this PowerShell session
setx SF_MPXJ_HOME "$PWD\tools\mpxj"         # persist for new sessions
```

Either script downloads MPXJ + dependencies into `tools/mpxj/lib`, compiles the
converter into `tools/mpxj/classes`, and `SF_MPXJ_HOME` makes both the CLI and the
**web UI** parse native `.mpp` / `.mpx` uploads. To have it ready in every session,
set `SF_MPXJ_HOME` and run the setup script from your environment's setup /
SessionStart hook (the one-click launchers read `SF_MPXJ_HOME` if you set it there).

> **Windows users have a second option — no Java required.** If MS Project is
> installed, you can read native `.mpp` through it via **COM automation** instead of
> MPXJ: in the web UI's *Native .mpp / .mpx reader* choice, pick **MS Project**. See
> ["Choosing the reader in the web UI"](#choosing-the-reader-in-the-web-ui) below.

## Manual setup (equivalent, verified with MPXJ 16.2.0, Java 21)

Resolve MPXJ + its dependencies into a `lib/` directory and compile the tiny
converter in `tools/mpxj/`. `pom.xml` is shown inline because the repo's
data-sovereignty `.gitignore` blocks all `*.xml` files — create it locally:

```xml
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>local</groupId><artifactId>mpxj-runner</artifactId><version>1.0</version>
  <packaging>jar</packaging>
  <properties><maven.compiler.release>21</maven.compiler.release></properties>
  <dependencies>
    <dependency>
      <groupId>net.sf.mpxj</groupId><artifactId>mpxj</artifactId><version>16.2.0</version>
    </dependency>
  </dependencies>
</project>
```

```sh
cd tools/mpxj
# 1. fetch MPXJ + transitive deps (POI, etc.) into ./lib
mvn -q dependency:copy-dependencies -DoutputDirectory=lib -DincludeScope=runtime
# 2. compile the converter against them
javac -cp 'lib/*' -d classes MpxjToMspdi.java
```

## Wire it up

Point the importer at the converter via **one** environment variable. The
`{input}` / `{output}` tokens are substituted with file paths (no shell is used;
Java expands the `lib/*` classpath wildcard itself):

```sh
export SF_MPXJ_CMD="java -cp $PWD/classes:$PWD/lib/* MpxjToMspdi {input} {output}"
```

Resolution order is `SF_MPXJ_CMD` > `SF_MPXJ_JAR` > `SF_MPXJ_HOME` > the
**auto-discovered default** `tools/mpxj/` (used when none of the env vars are set
and that directory has been built). The quick setup above relies on auto-discovery;
the env vars are only for custom install locations or a single runnable jar
(`SF_MPXJ_JAR=/path/to.jar`).

Then in Python:

```python
from schedule_forensics.importers.mpp_mpxj import parse_mpp
schedule = parse_mpp("/path/to/project.mpp")   # -> schedule_forensics.schemas.Schedule
```

## Choosing the reader in the web UI

The upload form offers a **Native .mpp / .mpx reader** choice that applies only to
those binary formats (`.xer` and MS Project XML ignore it):

- **MPXJ (Java helper, cross-platform — default):** routes the upload through the
  MPXJ subprocess configured above. Works on any OS with Java; requires the
  `SF_MPXJ_*` setup. If MPXJ is not configured, the upload fails closed with an
  actionable message (it does not silently fall back).
- **MS Project (COM automation — Windows only):** drives your locally installed MS
  Project to open the file and read it directly (no Java needed). Off-Windows, or
  without MS Project / `pywin32`, this fails closed with a message pointing you back
  to the MPXJ / XML path (`ComUnavailableError`). The COM reader opens the file
  **read-only** and never modifies your source `.mpp` (CLAUDE.md COM gotcha 7).

Both readers run **entirely locally** — no schedule data leaves the machine (LAW 1).
The uploaded bytes are written to a private, auto-deleted temp file only for the
duration of the parse (both readers need a real file path).

> **Fidelity note (LAW 2):** the two readers can differ on edge cases (MPXJ's `.mpp`
> reader is an independent re-implementation; COM uses MS Project's own engine). On
> Windows with MS Project installed, **MS Project (COM) is the higher-fidelity
> reference** for `.mpp`; MPXJ is the portable path everywhere else. The COM ↔ MPXJ
> conformance check on a shared fixture is part of the user's local Windows
> validation (it cannot run in CI — see docs/HAZARDS.md, H-NO-COM-HERE).

## Verifying the wiring

With `SF_MPXJ_CMD` set, run the opt-in integration test (skipped by default so
CI stays green without the toolchain):

```sh
SF_MPXJ_INTEGRATION=1 pytest tests/test_importer_mpp_mpxj.py::test_real_mpxj_reads_a_fixture
```

## Notes on fidelity (LAW 2)

- The conversion is `native → MSPDI → Schedule`. MSPDI fidelity (durations as
  ISO-8601, link types, constraints) is covered by the MSPDI importer tests.
- A **true binary `.mpp`** cannot be authored on Linux (MPXJ reads `.mpp` but
  does not write it, and there is no MS Project here), so the `.mpp` path itself
  must be validated on a machine with a real `.mpp`. The subprocess→MPXJ→parse
  pipeline is otherwise fully exercised here (hermetically via a stub converter,
  and live via MPXJ reading a real MSPDI file).
- MPXJ's reader sniffs the input format; hand-authored minimal fixtures (e.g. the
  synthetic `.xer`) may be rejected as not well-formed even when the lenient
  pure-Python importer accepts them. Feed MPXJ files exported by real tools.
