# FIDELITY-COMPROMISE — native file importers (.xml / .xer) are best-effort

Native import of MS Project XML (MSPDI) and Primavera P6 `.xer` was added so users can load real
files. **No real vendor sample files were available** when these were written, so the parsers were
reconstructed from format knowledge and tested only against hand-crafted samples. They are
**best-effort** — the UI labels them so, and loads the result into the editable box for review.

Known limitations / assumptions (verify against your real files):

- **`.mpp` is not supported at all.** It is a proprietary binary; reading it needs MS Project COM
  (Windows-only) or a heavyweight Java library, neither of which fits the portable app. Workflow:
  in MS Project, *File → Save As → XML*, then import the `.xml`.
- **MS Project XML units** taken on documented convention, not verified against a real file:
  `LinkLag` is read as **tenths of a minute** (`lag_minutes = LinkLag / 10`); `<Duration>` as ISO-8601
  working time; link `Type` 0/1/2/3 = FF/FS/SF/SS; `ConstraintType` 0–7 per the MSPDI table; WeekDay
  `DayType` 1–7 = Sun–Sat (mapped to ISO Mon–Sun).
- **XER calendars are NOT decoded.** The proprietary `clndr_data` blob is skipped; every imported XER
  calendar falls back to a standard 8h (or `day_hr_cnt`) / Mon–Fri / **no-holidays** calendar. This can
  shift working-day conversions and the calendar-sensitive metrics.
- **XER constraint codes** (`CS_*`) are mapped best-effort; unrecognised codes default to ASAP.
- **No baseline import from XER**, so Metrics 11/13/14 (which need a baseline finish) are *skipped*
  for XER imports rather than guessed. MS Project XML baseline import uses Baseline number 0 only.
- **Resources:** MS Project XML resources come via `<Assignments>`; XER resource assignments are not
  imported (so Metric 10 will flag everything as unresourced for XER).
- **Progress/data-date scheduling** is still not modelled (see `FIDELITY-DECISION-dcma-coverage.md`),
  so forecast-dependent results on an in-progress imported schedule carry that same caveat.

Bottom line: these importers get a real file *into* the tool for a first look; for forensic use,
spot-check the imported tasks/durations/links/dates against the source.
