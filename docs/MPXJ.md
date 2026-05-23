# Native `.mpp` ingestion via MPXJ (optional, user-provided)

`importers/mpp_mpxj.py` reads native MS Project `.mpp` (and `.mpx`, `.xer`,
MSPDI) files by invoking **MPXJ** (a Java library) as an **out-of-process,
killable subprocess** that converts the file to MSPDI XML; the proven pure-Python
`parse_msp_xml` then reads that. The JVM never runs inside the Python process
(Commandment 1: **never in-process JPype**).

MPXJ is an **optional runtime dependency** — like the Windows COM path, it is
discovered at runtime and is **not bundled** (keeps the repo and CI lean). If it
is not configured, `parse_mpp` raises `ImporterError` (fail closed); the rest of
the tool is unaffected.

> **LAW 1:** MPXJ runs locally and does no network I/O. The conversion writes a
> temp MSPDI file that is deleted immediately after parsing; no schedule data
> leaves the machine.

## One-time setup (verified with MPXJ 16.2.0, Java 21)

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

(Alternatively, build a single runnable jar and set `SF_MPXJ_JAR=/path/to.jar`;
the importer then runs `java -jar <jar> {input} {output}`.)

Then in Python:

```python
from schedule_forensics.importers.mpp_mpxj import parse_mpp
schedule = parse_mpp("/path/to/project.mpp")   # -> schedule_forensics.schemas.Schedule
```

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
