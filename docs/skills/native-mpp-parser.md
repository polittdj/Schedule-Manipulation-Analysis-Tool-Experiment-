# SKILL: Native Microsoft Project (.mpp) File Parser and Forensic Analyzer

> Reference skill for reading and forensically analyzing native binary Microsoft Project `.mpp`
> files (and Primavera `.xer`/`.xml`/`.mpx`). This repository **implements** the approach below in
> `app/parsers/mpp.py` (MPXJ-backed) and `app/parsers/{msp_xml,xer}.py` (pure-Python).
>
> NOTE: a user's machine-specific environment section was intentionally genericized before storing
> this in the repo (it contained personal paths / org-internal program references). Configure your
> local JDK path and handle controlled data per your organization's policy — parse sensitive
> schedules locally; never upload them to third-party cloud services.

## 1. Ground truth
1. `.mpp` is a **proprietary, closed, binary OLE compound document**. No pure-Python library reads it reliably.
2. `pandas`, `openpyxl`, etc. cannot parse it.
3. The robust, industry-standard reader is the **MPXJ** library (open source, LGPL) — it reads `.mpp`
   (MSP 98 → 365), `.xer`, `.xml` (MSPDI / Primavera PMXML), and `.mpx`.
4. Invoke MPXJ from Python via the `mpxj` package, which bridges to a JVM through **JPype**.
5. Requirements: (a) a JVM (Java 17+), (b) MPXJ jars (bundled with the `mpxj` pip package), (c) `pip install mpxj`.

Do not claim `.mpp` is "unparseable." The correct response is "install MPXJ and parse it"; only if
Java truly can't run, degrade gracefully (Section 7).

## 2. Environment
```python
import mpxj            # bundles the MPXJ jars
mpxj.startJVM()        # starts the JVM with those jars on the classpath
from org.mpxj.reader import UniversalProjectReader   # NOTE: org.mpxj (MPXJ 13+); older docs say net.sf.mpxj
```
Install: `pip install mpxj` (pulls `JPype1`). Java install: `apt-get install -y default-jre-headless`
(Debian), `brew install openjdk@21` (macOS), or a portable OpenJDK on Windows. If the sandbox can't
run Java, go to Section 7.

## 3. Canonical parse routine (verified API)
```python
import mpxj
mpxj.startJVM()
from org.mpxj import TimeUnit
from org.mpxj.reader import UniversalProjectReader

project = UniversalProjectReader().read(path)          # .mpp/.xer/.xml/.mpx
props   = project.getProjectProperties()               # getName/getStartDate/getStatusDate/getMinutesPerDay
for t in project.getTasks():
    if t is None or t.getUniqueID() == 0 or t.getSummary():
        continue
    minutes = t.getDuration().convertUnits(TimeUnit.MINUTES, props).getDuration()  # unit-safe
    ctype   = str(t.getConstraintType())   # AS_SOON_AS_POSSIBLE / MUST_START_ON / START_NO_EARLIER_THAN / ...
    for link in t.getPredecessors() or []:
        pred = link.getPredecessorTask().getUniqueID()   # successor = link.getSuccessorTask()
        rtype = str(link.getType())                       # FS / SS / FF / SF
        lag   = link.getLag().convertUnits(TimeUnit.MINUTES, props).getDuration()
```
Notes: wrap MPXJ values in `str()`/`int()`/`float()`; use `Duration.convertUnits(MINUTES, props)` so
days/weeks resolve via the project's minutes-per-day; skip the UID-0 project summary and summary
roll-ups; relationship/constraint values come back as enum names.

## 4. Forensic analyses to offer proactively
- **DCMA 14-Point Assessment** (this repo implements all 14 in `app/metrics/`): 1 Logic ≥95%,
  2 Leads <5%, 3 Lags <5%, 4 Relationship Types ≥90% FS, 5 Hard Constraints <5%, 6 High Float <5%
  (>44 wd), 7 Negative Float 0, 8 High Duration <5% (>44 wd), 9 Invalid Dates, 10 Resources,
  11 Missed Tasks <5%, 12 Critical Path Test, 13 CPLI ≥0.95, 14 BEI ≥0.95.
- **UID-targeted CPM / driving path** — always ask *which UID* to trace to; don't default to "the last task."
- **Dual-schedule comparison** (baseline vs update / as-planned vs as-built), joined on **UID**.
- **Manipulation detection** — pattern library: logic deletion on the driving path; duration
  compression; remaining-duration gaming; artificial progress inflation; progress backdating;
  constraint relaxation/removal; relationship-type change (FS→SS/FF); lag reduction; negative-lag
  insertion; out-of-sequence progress. Score severity 1–5 → weighted risk 0–100.
- **Float erosion** and **logic density / open-end detection**.

## 5. Output conventions
Lead with the answer; then an evidence table; then forensic interpretation; then the next step.
**Cite UIDs, not names** (UID is invariant; Name is not).

## 6. Dual-file convention
Earlier status date = "Schedule A" (baseline/as-planned); later = "Schedule B" (current/as-built).
Honor explicit user labels. Always state which file is which.

## 7. Degraded mode (no Java)
Do not fake a parse. Say Java/MPXJ isn't available, then: "In MS Project, *File → Save As → XML*, and
load that XML" (pure-Python parseable). For Primavera, export `.xer`/`.xml`. Offer a local script for
users who have Java on their own machine. Never fabricate task names, durations, or dates.

## 8. Local environment (genericize per user)
Set your JDK location and `PATH`, and point at your local forensic repo. Treat SBU/ITAR/CUI schedules
as sensitive: parse locally, never upload to third-party cloud parsing services.

## 9. Common pitfalls
Don't claim a parse from raw bytes; don't invent UIDs/durations; don't default CPM to the last task;
don't trust MSP's `Critical` flag for a UID-target analysis (recompute); don't drop duration units;
don't treat the UID-0 summary as the project's true start/finish.

## 10. Invocation triggers
A `.mpp` upload; mentions of MS Project / native `.mpp`; CPM / critical path / driving path; forensic
scheduling / delay claims / TIA / windows analysis; UID targeting; two-file comparison; DCMA; schedule
manipulation. On trigger: verify environment → parse (or degrade honestly) → offer the analyses.

## 11. How this repo uses it
`app/parsers/mpp.py` implements Sections 2–3 (MPXJ via `org.mpxj`, unit-safe conversion, UID-0/summary
skipping, FS/SS/FF/SF + lag, constraints, progress, resources) and maps to `app/models.Schedule`;
`app/analysis.py` then runs the DCMA-14 metrics + health score. MPXJ is optional
(`requirements-mpp.txt`, needs Java); without it the tool reads `.xml`/`.xer` in pure Python and tells
`.mpp` users to *Save As → XML*.
