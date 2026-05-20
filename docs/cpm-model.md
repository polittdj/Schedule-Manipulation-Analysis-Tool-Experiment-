# CPM model

## Time representation
All schedule times are **integer working-minute offsets** from `project_start` (offset 0).
Durations (`Task.duration_minutes`) and relation `lag_minutes` are **working-time minutes**.
The engine is pure integer arithmetic on these offsets, so:
- the end-of-day / start-of-next-day boundary ambiguity never enters the math (a predecessor
  finish and the successor start it drives share one offset);
- total slack `= LS - ES = LF - EF` is exact, and converts to working days by dividing by
  `hours_per_day * 60` at presentation only.

Wall-clock dates are produced (when needed) by `calendar_math.add_working_minutes`, which lays
working minutes onto real dates, skipping non-working weekdays and holidays.

## Forward pass (earliest)
For task `T` with duration `d`, over each incoming relation from predecessor `P` with lag `L`:

| type | candidate ES(T) |
|------|-----------------|
| FS   | `EF(P) + L`     |
| SS   | `ES(P) + L`     |
| FF   | `EF(P) + L - d` |
| SF   | `ES(P) + L - d` |

`ES(T) = max(0, max candidate)`, `EF(T) = ES(T) + d`. `project_finish = max EF`.

## Backward pass (latest)
Sinks get `LF = project_finish`. Over each outgoing relation to successor `S` with lag `L`:

| type | candidate LF(T)      |
|------|----------------------|
| FS   | `LS(S) - L`          |
| SS   | `LS(S) - L + d`      |
| FF   | `LF(S) - L`          |
| SF   | `LF(S) - L + d`      |

`LF(T) = min candidate`, `LS(T) = LF(T) - d`.

## Slack & critical path
- **Total slack** = `LS - ES`. **Critical path** = tasks with total slack 0 (ascending UniqueID).
- **Free slack** = `min` over successors of the gap to the successor's *early* dates
  (FS: `ES(S) - (EF(T)+L)`, SS: `ES(S) - (ES(T)+L)`, FF: `EF(S) - (EF(T)+L)`,
  SF: `EF(S) - (ES(T)+L)`); sinks get `project_finish - EF(T)`.
- Topological order is Kahn's algorithm with the ready-queue tie-broken by ascending
  UniqueID (deterministic). A logic cycle raises `CPMError`.

## Worked examples (8h/day = 480 min; values shown in days)

### Example 1 — merge + a slack branch (all FS, lag 0)
Durations: A=2, B=3, C=2, D=4, E=1. Logic: A->B, A->C, B->D, C->D, D->E.

| task | ES | EF | LS | LF | total slack | free slack |
|------|----|----|----|----|-------------|------------|
| A | 0 | 2 | 0 | 2 | 0 | 0 |
| B | 2 | 5 | 2 | 5 | 0 | 0 |
| C | 2 | 4 | 3 | 5 | **1** | **1** |
| D | 5 | 9 | 5 | 9 | 0 | 0 |
| E | 9 | 10 | 9 | 10 | 0 | 0 |

`project_finish = 10`. **Critical path = [A, B, D, E].** C carries exactly 1 working day of
slack: B (3d) drives D, so C (2d) on the parallel arm can slip 1 day without delaying D.

### Example 2 — mixed relationship types with lag
Durations: A=4, B=6, C=5. Logic: A->B SS+2, B->C FF+1.

| task | ES | EF | LS | LF | total slack |
|------|----|----|----|----|-------------|
| A | 0 | 4 | 0 | 4 | 0 |
| B | 2 | 8 | 2 | 8 | 0 |
| C | 4 | 9 | 4 | 9 | 0 |

`project_finish = 9`. **Critical path = [A, B, C]** (all critical). SS makes B start 2 days
after A starts; FF makes C finish 1 day after B finishes; note C's EF (9) trails B's EF (8),
which an FS-only engine would get wrong.
