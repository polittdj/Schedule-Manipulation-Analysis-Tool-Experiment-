"""Driving-path / driving-slack trace (SSI "driving slack" methodology).

This module answers the forensic question "what chain of activities is actually
*driving* the project finish date right now?" -- the longest path expressed not
as ``total_float <= 0`` (the CPM critical path) but as an unbroken chain of
relationships whose **relationship free float is zero**. A relationship with
zero free float is *binding*: the predecessor cannot slip by even one minute
without moving the successor's early dates. SSI/Steelray call this "driving
slack"; the driving path is the back-trace through binding links from the
activity that lands on the project finish.

Why this is distinct from ``CPMResult.critical_path`` (and worth its own module):
the critical path is the *set* of float<=0 activities; the driving path is an
*ordered chain* through binding logic. In a network with parallel float<=0
branches, or with imposed/constraint-driven negative float, the two can differ.
The driving path is the chain testimony refers to as "the path to completion".

Source (Law 2 / parity honesty): the relationship-free-float formulas and the
"zero slack == driving" rule are modeled on the Steelray/SSI driving-slack
methodology (docs/REFERENCES.md key: ``SSI-SLACK``). The methodology is *cited
in practice*; an exact page anchor is **source-pending** (the SSI document is
not yet in ``docs/sources/`` -- see REFERENCES.md). The four relationship-slack
formulas are identical to those used by the frozen CPM engine
(``cpm._link_slack``); they are re-derived here rather than importing a private
name, and a test pins them against that engine to prevent drift (H-DRIFT-2).

The relationship-free-float values for SS/FF/SF are measured at each link's
governing event; reference tools vary on non-FS free float, so per-link slack
for those types carries the same documented caveat the CPM engine carries. The
FS case -- by far the dominant link type in real schedules -- is the standard
free float and is exact.

Units: every value is an INTEGER WORKING-MINUTE offset/quantity on the same axis
as :mod:`schedule_forensics.cpm` (480 working minutes == one 8-hour day). No
wall-clock dates are introduced here.

Parity status: the driving-path *trace itself* is a standard SSI capability, not
a tool-original extension; it is therefore not flagged ``is_extension``. It is
nonetheless ``source-pending`` on its page anchor until the SSI document lands.
"""

from __future__ import annotations

from dataclasses import dataclass

from schedule_forensics.cpm import CPMResult, compute_cpm
from schedule_forensics.schemas import RelationType, Schedule


@dataclass(frozen=True)
class LinkSlack:
    """Relationship free float for one logic link P -> S, on the working-minute axis.

    ``slack_minutes`` is how far the predecessor side may slip before this single
    link begins to push the successor's early dates. ``is_driving`` is true iff
    ``slack_minutes == 0`` (the link is binding -- "driving slack" in SSI terms).
    Links touching a summary task are never emitted (summaries are not real
    activities and are absent from ``CPMResult.timings``).
    """

    predecessor_id: int
    successor_id: int
    type: RelationType
    slack_minutes: int
    is_driving: bool


@dataclass(frozen=True)
class DrivingPathResult:
    """The driving-path trace for a single schedule version.

    ``driving_chain`` is the ordered tuple of ``unique_id`` values from the
    chain's start activity to the activity that lands on the project finish
    (start -> finish order). It is empty for a schedule with no schedulable
    activities. ``link_slacks`` is the per-link relationship-free-float record
    for every non-summary logic link, in a deterministic order.
    """

    driving_chain: tuple[int, ...]
    link_slacks: tuple[LinkSlack, ...]


def _relationship_free_float(
    rel: RelationType,
    es_p: int,
    ef_p: int,
    es_s: int,
    ef_s: int,
    lag: int,
) -> int:
    """Relationship free float for link ``P -> S`` (SSI driving-slack semantics).

    Identical to the frozen CPM engine's ``_link_slack`` (re-derived, not
    imported, to avoid depending on a private name; pinned by a parity test):

    * FS: ``es_S - (ef_P + lag)``
    * SS: ``es_S - (es_P + lag)``
    * FF: ``ef_S - (ef_P + lag)``
    * SF: ``ef_S - (es_P + lag)``
    """
    if rel is RelationType.FS:
        return es_s - (ef_p + lag)
    if rel is RelationType.SS:
        return es_s - (es_p + lag)
    if rel is RelationType.FF:
        return ef_s - (ef_p + lag)
    return ef_s - (es_p + lag)  # SF


def analyze_driving_path(schedule: Schedule, result: CPMResult | None = None) -> DrivingPathResult:
    """Trace the driving path to project completion (SSI driving-slack method).

    Computes the CPM internally when ``result`` is ``None`` so callers may either
    reuse an existing :class:`~schedule_forensics.cpm.CPMResult` or pass just the
    schedule. Raises whatever :func:`~schedule_forensics.cpm.compute_cpm` raises
    on an unschedulable network (a cycle, or a deferred constraint) -- this module
    never invents timings.

    Algorithm:

    1. For every logic link whose *both* endpoints are scheduled activities
       (summaries are skipped -- they are absent from ``result.timings``), compute
       the relationship free float. A link is **driving** iff that value is 0.
    2. Identify the finish activity: a scheduled task whose ``early_finish``
       equals ``result.project_finish``. Among those, a task that itself *drives*
       another task (has an outgoing driving link) is not the project-completion
       activity -- it is mid-chain -- so it is excluded; the project finish is
       the driving *sink*. (Example: a zero-duration finish milestone shares the
       project-finish offset with its immediate driving predecessor; the
       milestone, not the predecessor, is the endpoint.) On a tie among the
       remaining sink candidates, the smallest ``unique_id`` is chosen for
       determinism. If no sink survives (every finish-offset task drives another
       -- only possible in a cycle the CPM would already reject), the smallest
       ``unique_id`` at the finish offset is used as a defensive fallback.
    3. Walk backward from the finish activity: at each step, among the current
       task's *incoming driving* links, follow the predecessor with the smallest
       ``unique_id``; stop when a task has no incoming driving link. Reverse the
       collected ids to return them in start -> finish order.

    An empty / activity-free schedule yields an empty chain and no link slacks.
    """
    cpm = result if result is not None else compute_cpm(schedule)
    timings = cpm.timings

    # 1. Relationship free float per link, skipping any link that touches a
    #    summary task (those endpoints are not in ``timings``). Iterate the
    #    schedule's relations in their declared order for a stable emission order.
    link_slacks: list[LinkSlack] = []
    # Incoming driving predecessors per successor, deduplicated, for the back-walk.
    driving_predecessors: dict[int, set[int]] = {}
    # Tasks that *drive* a successor (have >=1 outgoing driving link): mid-chain,
    # never the project-completion sink even when they share the finish offset.
    drives_a_successor: set[int] = set()
    for rel in schedule.relations:
        pred_t = timings.get(rel.predecessor_id)
        succ_t = timings.get(rel.successor_id)
        if pred_t is None or succ_t is None:
            continue
        slack = _relationship_free_float(
            rel.type,
            pred_t.early_start,
            pred_t.early_finish,
            succ_t.early_start,
            succ_t.early_finish,
            rel.lag_minutes,
        )
        is_driving = slack == 0
        link_slacks.append(
            LinkSlack(
                predecessor_id=rel.predecessor_id,
                successor_id=rel.successor_id,
                type=rel.type,
                slack_minutes=slack,
                is_driving=is_driving,
            )
        )
        if is_driving:
            driving_predecessors.setdefault(rel.successor_id, set()).add(rel.predecessor_id)
            drives_a_successor.add(rel.predecessor_id)

    # 2. Finish activity: a task landing on the project finish that is a driving
    #    *sink* (does not itself drive a successor). On a tie, smallest unique_id.
    at_finish = sorted(tid for tid, t in timings.items() if t.early_finish == cpm.project_finish)
    if not at_finish:
        # No schedulable activities (empty/all-summary schedule). Empty trace.
        return DrivingPathResult(driving_chain=(), link_slacks=tuple(link_slacks))
    sinks = [tid for tid in at_finish if tid not in drives_a_successor]
    current = sinks[0] if sinks else at_finish[0]

    # 3. Back-walk through binding links; guard against pathological revisits.
    chain_reversed: list[int] = [current]
    seen: set[int] = {current}
    while True:
        incoming = driving_predecessors.get(current)
        if not incoming:
            break
        nxt = min(incoming)
        if nxt in seen:  # defensive: never loop (CPM already rejects true cycles)
            break
        chain_reversed.append(nxt)
        seen.add(nxt)
        current = nxt

    return DrivingPathResult(
        driving_chain=tuple(reversed(chain_reversed)),
        link_slacks=tuple(link_slacks),
    )


# ── Top-K paths to a user-chosen target (critical / secondary / tertiary) ─────
#
# When the operator picks a SPECIFIC target activity (e.g. a contract milestone
# that is NOT the project's overall finish), they typically want three things:
# the longest activity chain ending there (the "critical path *to that target*"),
# plus the next two longest alternative chains for "secondary" and "tertiary"
# path analysis. The K=1 result is the standard CPM-longest-path concept (sum of
# activity durations along the chain); K=2/3 are a TOOL-ORIGINAL extension --
# they are not a reference-tool definition and are labelled accordingly. The
# enumeration uses a topological-order DP over the schedule's relation DAG,
# tracking the top-K longest paths ending at each node in O((V + E) * K).


@dataclass(frozen=True)
class PathToTarget:
    """One ordered chain of activity UIDs ending at the chosen target.

    ``task_uids`` are in start -> target order (matching ``driving_chain``).
    ``duration_minutes`` is the sum of activity ``duration_minutes`` along the
    chain (working minutes). ``is_driving`` is true iff EVERY relationship on
    the chain has zero relationship free float (the chain is an unbroken SSI
    binding chain end-to-end).
    """

    task_uids: tuple[int, ...]
    duration_minutes: int
    is_driving: bool


@dataclass(frozen=True)
class PathsToTargetResult:
    """The top-K longest activity chains ending at ``target_uid``.

    ``paths`` is ranked by ``duration_minutes`` descending (ties broken by the
    smallest start-task ``unique_id``). Up to ``k`` entries; an empty tuple when
    the target has no reachable predecessors and is a root activity itself
    (then the single-element path ``(target_uid,)`` IS returned for ``k >= 1``).
    """

    target_uid: int
    paths: tuple[PathToTarget, ...]


def analyze_paths_to_target(
    schedule: Schedule,
    target_uid: int,
    result: CPMResult | None = None,
    *,
    k: int = 3,
) -> PathsToTargetResult:
    """Top-``k`` longest activity chains terminating at ``target_uid``.

    Critical / secondary / tertiary path analysis for a chosen end-task. A
    "path" is an ordered chain of non-summary scheduled activities connected
    by predecessor->successor relations in the schedule; the chain's length
    is the sum of activity ``duration_minutes`` along it (working minutes).
    Paths are ranked by length descending, ties broken by the smallest start
    UID for determinism.

    The K=1 path matches the standard CPM-longest-path concept; K=2/3 are a
    **tool-original extension** (parity honesty -- no single reference-tool
    definition for "second / third critical path").

    Raises :class:`ValueError` if ``target_uid`` is not a scheduled activity
    in the CPM result (missing, a summary, or unschedulable). Raises if ``k``
    is negative. Returns an empty :class:`PathsToTargetResult` when ``k == 0``.
    """
    if k < 0:
        raise ValueError(f"k must be non-negative; got {k}")
    cpm = result if result is not None else compute_cpm(schedule)
    timings = cpm.timings
    if target_uid not in timings:
        raise ValueError(
            f"target UID {target_uid} is not a scheduled activity in this schedule "
            "(it may be missing, a summary, or unschedulable)."
        )
    if k == 0:
        return PathsToTargetResult(target_uid=target_uid, paths=())

    duration_by_id: dict[int, int] = {t.unique_id: t.duration_minutes for t in schedule.tasks}

    # Predecessor map (non-summary endpoints only) + per-edge "is driving" flag.
    preds_by_succ: dict[int, list[int]] = {}
    edge_drives: dict[tuple[int, int], bool] = {}
    for rel in schedule.relations:
        pred_t = timings.get(rel.predecessor_id)
        succ_t = timings.get(rel.successor_id)
        if pred_t is None or succ_t is None:
            continue
        preds_by_succ.setdefault(rel.successor_id, []).append(rel.predecessor_id)
        slack = _relationship_free_float(
            rel.type,
            pred_t.early_start,
            pred_t.early_finish,
            succ_t.early_start,
            succ_t.early_finish,
            rel.lag_minutes,
        )
        edge_drives[(rel.predecessor_id, rel.successor_id)] = slack == 0

    # Topo-sort timings.keys() via Kahn's algorithm (CPM rejects cycles, so this
    # always completes; the assertion below guards a never-should-happen state).
    in_deg: dict[int, int] = {tid: len(preds_by_succ.get(tid, [])) for tid in timings}
    succs_by_pred: dict[int, list[int]] = {}
    for succ, preds in preds_by_succ.items():
        for p in preds:
            succs_by_pred.setdefault(p, []).append(succ)
    ready: list[int] = sorted(tid for tid, d in in_deg.items() if d == 0)
    ordered: list[int] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for s in sorted(succs_by_pred.get(node, [])):
            in_deg[s] -= 1
            if in_deg[s] == 0:
                ready.append(s)
    assert len(ordered) == len(timings), "internal: topo sort failed despite acyclic CPM"

    # DP: at each node, keep the top-K longest paths ending there.
    # Entry = (duration_minutes, task_uids in start->node order, all_driving_flag)
    paths_at: dict[int, list[tuple[int, tuple[int, ...], bool]]] = {}
    for node in ordered:
        node_dur = duration_by_id.get(node, 0)
        preds = preds_by_succ.get(node, [])
        if not preds:
            paths_at[node] = [(node_dur, (node,), True)]
            continue
        candidates: list[tuple[int, tuple[int, ...], bool]] = []
        for p in preds:
            link_driving = edge_drives.get((p, node), False)
            for dur_p, chain_p, drv_p in paths_at.get(p, []):
                candidates.append((dur_p + node_dur, (*chain_p, node), drv_p and link_driving))
        candidates.sort(key=lambda c: (-c[0], c[1][0]))
        paths_at[node] = candidates[:k]

    final = paths_at.get(target_uid, [])
    return PathsToTargetResult(
        target_uid=target_uid,
        paths=tuple(
            PathToTarget(task_uids=chain, duration_minutes=dur, is_driving=adr)
            for dur, chain, adr in final
        ),
    )
