from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

from .model import Rule, Worker

MUST = 2

# soft-rule violation penalty applied when choosing a candidate worker
SOFT_PENALTY = 300
TRY_BONUS = 1000
BASE_SCORE = 10
FAIRNESS_WEIGHT = 5

SEARCH_BUDGET_SECONDS = 4.0
SEARCH_CANDIDATE_BRANCH_LIMIT = 8
CPSAT_TIME_LIMIT_SECONDS = 6.0


@dataclass
class SolverResult:
    # day -> shift -> assigned worker names (joined for display)
    entries: dict[str, dict[str, str]] = field(default_factory=dict)
    # (day, shift, reason) for slots that could not be (fully) filled
    unfilled: list[tuple[str, str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # per-slot decision trace (in processing order)
    traces: list[dict] = field(default_factory=list)
    # final assignment state: worker name -> _WorkerState
    state: dict = field(default_factory=dict)


def _worker_rule(worker: Worker, key: str) -> Rule | None:
    for r in worker.rules:
        if r.type == key and r.enabled:
            return r
    return None


def _global_rule(global_rules: list[Rule], key: str) -> Rule | None:
    """Effective rule for a type: must-priority rules win over duplicates."""
    found = [
        r for r in (global_rules or [])
        if r.type == key and r.enabled
    ]
    if not found:
        return None
    for r in found:
        if r.priority == MUST:
            return r
    return found[0]


def _required_counts(global_rules: list[Rule], shift_names: list[str]) -> dict[str, int]:
    """Required workers per shift, from min_workers_per_shift rule.
    Shifts missing from the rule default to 1; explicit values (incl. 0)
    are honored."""
    rule = _global_rule(global_rules, "min_workers_per_shift")
    counts = dict(rule.params.get("counts", {})) if rule else {}
    return {s: int(counts[s]) if s in counts else 1 for s in shift_names}


@dataclass
class _WorkerState:
    orders: list[int] = field(default_factory=list)
    days: set[str] = field(default_factory=set)


def _per_worker_cap(
    worker: Worker, num_slots: int, rest_gap: int | None
) -> int | None:
    """Hard cap on a worker's assignment count: the rest-rule arithmetic
    bound tightened by must-priority max rules. None = unlimited."""
    rest_cap = (num_slots - 1) // rest_gap + 1 if rest_gap else num_slots
    cap: int | None = rest_cap
    r = _worker_rule(worker, "max_week_shifts")
    if r is not None and r.priority == MUST:
        cap = min(cap, int(r.params.get("n", 0)))
    return cap


def _capacity_stats(
    workers: list[Worker], days: list[str], shift_names: list[str],
    required_counts: dict[str, int], rest_gap: int | None,
) -> tuple[int, int, int]:
    """Returns (demand, capacity, max_per_worker).

    demand = total required assignments for the week.
    capacity = what the must rules allow all workers combined.
    """
    num_slots = len(days) * len(shift_names)
    max_per_worker = (num_slots - 1) // rest_gap + 1 if rest_gap else num_slots
    capacity = 0
    for w in workers:
        if not any(w.is_available(d, s) for d in days for s in shift_names):
            continue
        cap = _per_worker_cap(w, num_slots, rest_gap)
        capacity += cap if cap is not None else num_slots
    demand = sum(required_counts.values()) * len(days)
    return demand, capacity, max_per_worker


def _impossible_by_capacity(
    workers: list[Worker], days: list[str], shift_names: list[str],
    required_counts: dict[str, int], rest_gap: int | None,
) -> bool:
    """True when must rules (rest + per-worker caps) provably make full
    demand unreachable."""
    demand, capacity, _ = _capacity_stats(
        workers, days, shift_names, required_counts, rest_gap
    )
    return demand > capacity


def _cpsat_exact_cover(
    workers: list[Worker],
    days: list[str],
    shift_names: list[str],
    required_counts: dict[str, int],
    rest_rule: Rule | None,
    rest_gap: int | None,
    global_rules: list[Rule] | None,
) -> dict | None:
    """Exact solver with CP-SAT (requires ortools).

    Hard: availability, per-slot required counts (as upper bounds), must-
    priority worker caps (shifts + distinct days) and must-priority rest
    distance. Objective: maximize coverage, tie-break on "try" cells; with
    a fairness rule, load spread is only tightened when it provably keeps
    the coverage optimum.
    Returns {"entries", "state", "full", "coverage", "demand", "tries"} or
    None if ortools is missing or no feasible solution was found.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None

    n_shifts = len(shift_names)
    num_slots = len(days) * n_shifts
    demand, _, _ = _capacity_stats(workers, days, shift_names, required_counts, None)
    slot_of: dict[int, tuple[str, str]] = {}
    for di, day in enumerate(days):
        for si, shift in enumerate(shift_names):
            slot_of[di * n_shifts + si] = (day, shift)
    tries_of = {
        (w.name, o)
        for o, (day, shift) in slot_of.items()
        for w in workers
        if w.is_available(day, shift) and w.prefers(day, shift)
    }

    def build_model(spread_limit: int | None):
        m = cp_model.CpModel()
        x: dict[tuple[str, int], object] = {}
        for o, (day, shift) in slot_of.items():
            for w in workers:
                if w.is_available(day, shift):
                    x[w.name, o] = m.NewBoolVar(f"x_{w.name}_{o}")

        # hard worker caps and rest distance
        for w in workers:
            r = _worker_rule(w, "max_week_shifts")
            if r is not None and r.priority == MUST:
                cap = int(r.params.get("n", 0))
                m.Add(sum(v for (nm, _), v in x.items() if nm == w.name) <= cap)
            r_days = _worker_rule(w, "max_week_days")
            if r_days is not None and r_days.priority == MUST:
                n_d = int(r_days.params.get("n", 1))
                # distinct days used, via one indicator var per (worker, day)
                day_used = []
                for di, _day in enumerate(days):
                    day_vars = [x[w.name, di * n_shifts + si2]
                                for si2 in range(n_shifts)
                                if (w.name, di * n_shifts + si2) in x]
                    if not day_vars:
                        continue
                    y = m.NewBoolVar(f"day_{w.name}_{di}")
                    for v in day_vars:
                        m.Add(v <= y)
                    day_used.append(y)
                if day_used:
                    m.Add(sum(day_used) <= n_d)

        if rest_rule is not None and rest_rule.priority == MUST and rest_gap:
            for (nm, o), v in x.items():
                for d in range(1, rest_gap):
                    other = o + d
                    if other >= num_slots:
                        break
                    v2 = x.get((nm, other))
                    if v2 is not None:
                        m.Add(v + v2 <= 1)

        # coverage per slot — as upper bound so partial weeks stay solvable
        for o, (day, shift) in slot_of.items():
            m.Add(sum(v for (nm, oo), v in x.items() if oo == o)
                  <= required_counts[shift])

        # fairness: keep per-worker load spread within a limit
        if spread_limit is not None and _global_rule(global_rules, "fairness"):
            loads = {}
            for w in workers:
                vars_w = [v for (nm, _), v in x.items() if nm == w.name]
                loads[w.name] = m.NewIntVar(0, demand, f"load_{w.name}")
                if vars_w:
                    m.Add(loads[w.name] == sum(vars_w))
            max_load = m.NewIntVar(0, demand, "max_load")
            min_load = m.NewIntVar(0, demand, "min_load")
            for w in workers:
                m.Add(max_load >= loads[w.name])
                m.Add(min_load <= loads[w.name])
            m.Add(max_load - min_load <= spread_limit)

        # objective: maximize coverage first, then "try" cells
        # (try-cell weight must stay below one assignment's weight so
        # preferences can never beat coverage)
        obj = TRY_BONUS * sum(x.values())
        for (nm, o), v in x.items():
            if (nm, o) in tries_of:
                obj += 10 * v
        m.Maximize(obj)
        return m, x

    # base first; fairness spreads attempted only as refinement of an
    # optimally-proven base (avoids burning the time budget on levels that
    # can't reach the coverage optimum)
    m, x = build_model(None)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = CPSAT_TIME_LIMIT_SECONDS
    status = s.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    coverage = sum(s.Value(v) for v in x.values())
    base_optimal = status == cp_model.OPTIMAL

    chosen = (None, m, x, s)
    if base_optimal and _global_rule(global_rules, "fairness"):
        for spread in (2, 3):
            m_r, x_r = build_model(spread)
            s_r = cp_model.CpSolver()
            s_r.parameters.max_time_in_seconds = 3.0
            status_r = s_r.Solve(m_r)
            if status_r != cp_model.OPTIMAL:
                continue
            coverage_r = sum(s_r.Value(v) for v in x_r.values())
            if coverage_r == coverage:  # same optimum, fairer load
                chosen = (spread, m_r, x_r, s_r)
                break
    _, m, x, s = chosen

    entries = {d: {} for d in days}
    state = {w.name: _WorkerState() for w in workers}
    full = True
    for o, (day, shift) in slot_of.items():
        picked = sorted(
            nm for (nm, oo), v in x.items() if oo == o and s.Value(v) > 0
        )
        if picked:
            entries[day][shift] = ", ".join(picked)
            for nm in picked:
                state[nm].orders.append(o)
                state[nm].days.add(day)
        elif required_counts[shift] > 0:
            full = False
    coverage = sum(
        1
        for d in entries
        for v in entries[d].values()
        if v
        for _w in v.split(", ")
    )
    tries = sum(1 for (nm, oo) in tries_of if s.Value(x[nm, oo]))
    return {"entries": entries, "state": state, "full": coverage >= demand,
            "coverage": coverage, "demand": demand, "tries": tries}


def solve(
    workers: list[Worker],
    days: list[str],
    shifts: dict[str, str],
    global_rules: list[Rule] | None = None,
) -> SolverResult:
    """Assign workers to day/shift slots honoring availability as a hard
    constraint, per-worker and global rules, and maximizing preferences.

    Strategy: greedy pass (try-cells first, most-constrained slots first);
    if slots remain unfilled, an exact solver (CP-SAT, then bounded DFS)
    tries to do better — replacement only when both coverage AND honored
    preferences improve (coverage always dominates).
    """
    result = SolverResult()
    result.entries = {day: {} for day in days}
    if not workers:
        for day in days:
            for shift in shifts:
                result.unfilled.append((day, shift, "אין עובדים במערכת"))
        return result

    shift_names = list(shifts)
    slots: list[tuple[int, int]] = [
        (di, si) for di in range(len(days)) for si in range(len(shift_names))
    ]

    state: dict[str, _WorkerState] = {w.name: _WorkerState() for w in workers}

    rest_rule = _global_rule(global_rules or [], "rest_shifts")
    rest_n = (rest_rule.params.get("n") if rest_rule else None)
    rest_soft: bool = bool(rest_rule and rest_rule.priority != MUST and rest_n)
    rest_gap: int | None = int(rest_n) + 1 if rest_n else None
    required_counts = _required_counts(global_rules or [], shift_names)

    # feasibility heads-up: must rules may make full demand unreachable
    if _impossible_by_capacity(
        workers, days, shift_names, required_counts, rest_gap
    ):
        demand, capacity, max_per_worker = _capacity_stats(
            workers, days, shift_names, required_counts, rest_gap
        )
        result.warnings.insert(0, (
            f"הסידור לא יוכל להתמלא במלואו: נדרשות {demand} שיבוצים "
            f"אך העובדים יכולים לכסות לכל היותר {capacity} "
            "לפי הכללים (הפסקה ומקסימומים). "
            "הפחת דרישות, הוסף עובדים, או הקל על הכללים."
        ))

    def count_assignments(entries: dict) -> int:
        return sum(
            1
            for d in entries
            for v in entries[d].values()
            if v
            for _w in v.split(", ")
        )

    def rebuild_unfilled(entries: dict) -> None:
        for d in days:
            for sh in shift_names:
                picked = entries[d].get(sh, "")
                count = len(picked.split(", ")) if picked else 0
                need = required_counts[sh]
                if count == 0:
                    result.unfilled.append(
                        (d, sh, f"נדרשים {need} עובדים – אין אף עובד זמין")
                    )
                elif count < need:
                    result.unfilled.append((d, sh, f"משובצו {count} מתוך {need}"))

    def honored_tries(st: dict[str, _WorkerState]) -> int:
        return sum(
            1
            for w in workers
            for day, cells in w.cell_priority.items()
            for shift in cells
            if day in days
            and shift in shift_names
            and days.index(day) * len(shift_names) + shift_names.index(shift)
            in st[w.name].orders
        )

    def violates_rest(name: str, order: int, st: dict | None = None) -> bool:
        if rest_gap is None:
            return False
        use = st if st is not None else state
        return any(abs(o - order) < rest_gap for o in use[name].orders)

    def candidates_for(
        day: str, shift: str, order: int, st: dict | None = None
    ) -> tuple[list[tuple[float, str]], list[tuple[str, str]]]:
        use = st if st is not None else state
        cands: list[tuple[float, str]] = []
        rejected: list[tuple[str, str]] = []
        for w in workers:
            wst = use[w.name]
            reason: str | None = None
            if not w.is_available(day, shift):
                reason = "לא זמין"
            else:
                score = BASE_SCORE

                if w.prefers(day, shift):
                    score += TRY_BONUS

                add_day = day not in wst.days
                cnt = len(wst.orders)
                n_days = len(wst.days)

                r_max_shifts = _worker_rule(w, "max_week_shifts")
                if r_max_shifts is not None:
                    n = int(r_max_shifts.params.get("n", 0))
                    if cnt + 1 > n:
                        if r_max_shifts.priority == MUST:
                            reason = f"מקסימום משמרות ({n})"
                        else:
                            score -= SOFT_PENALTY

                r_max_days = _worker_rule(w, "max_week_days")
                if r_max_days is not None and reason is None:
                    n = int(r_max_days.params.get("n", 0))
                    if add_day and n_days + 1 > n:
                        if r_max_days.priority == MUST:
                            reason = f"מקסימום ימים ({n})"
                        else:
                            score -= SOFT_PENALTY

                if rest_rule is not None and reason is None and violates_rest(w.name, order, use):
                    if not rest_soft:
                        reason = f"הפסקה (נדרש מרווח {rest_gap - 1})"
                    else:
                        score -= SOFT_PENALTY

                # fairness: prefer workers with fewer assigned shifts
                score -= cnt * FAIRNESS_WEIGHT
            if reason is not None:
                rejected.append((w.name, reason))
                continue
            cands.append((score, w.name))
        return cands, rejected

    # fill the most-constrained slots first, "try" cells prioritized
    def slot_key(slot: tuple[int, int]):
        di, si = slot
        day, shift = days[di], shift_names[si]
        cands = [
            w for w in workers
            if w.is_available(day, shift)
        ]
        has_try = any(w.prefers(day, shift) for w in cands)
        # shortage relative to demand; shift-major tiebreak spreads the
        # unavoidable gaps across shift kinds instead of dumping them all
        # on whichever kind happens to be processed last
        shortage = len(cands) - required_counts[shift]
        return (not has_try, max(0, shortage), si, di)

    # phase 1: slots that some worker marked as "try" are resolved first, so
    # the preference isn't starved by quota consumption elsewhere; phase 2
    # fills the remaining slots by general scoring
    slots_sorted = sorted(slots, key=slot_key)
    try_slots = [
        s for s in slots_sorted
        if any(w.prefers(days[s[0]], shift_names[s[1]]) for w in workers)
    ]
    other_slots = [s for s in slots_sorted if s not in try_slots]

    for di, si in try_slots + other_slots:
        day, shift = days[di], shift_names[si]
        order = di * len(shift_names) + si
        need = required_counts[shift]
        assigned: list[str] = []
        taken: set[str] = set()
        trace: dict = {"day": day, "shift": shift, "order": order, "need": need,
                       "picks": [], "blocked": [], "unfilled": None}
        for round_no in range(need):
            cands, rejected = candidates_for(day, shift, order)
            if round_no == 0:
                trace["blocked"] = [(nm, why) for nm, why in rejected]
            best: list[tuple[float, str]] = [
                (score, nm) for score, nm in cands if nm not in taken
            ]
            if not best:
                if not assigned:
                    result.unfilled.append(
                        (day, shift, f"נדרשים {need} עובדים – אין אף עובד זמין")
                    )
                    trace["unfilled"] = "אין אף עובד זמין"
                else:
                    result.unfilled.append(
                        (day, shift, f"משובצו {len(assigned)} מתוך {need}")
                    )
                    trace["unfilled"] = f"משובצו {len(assigned)} מתוך {need}"
                break
            best.sort(key=lambda t: (-t[0], t[1]))
            top_score = best[0][0]
            tied = [nm for sc, nm in best if sc == top_score]
            chosen = best[0][1]
            taken.add(chosen)
            state[chosen].orders.append(order)
            state[chosen].days.add(day)
            assigned.append(chosen)
            trace["picks"].append({"name": chosen, "score": top_score,
                                   "tied": tied})
            if need == 1 and len(tied) > 1:
                result.warnings.append(
                    f"{day} {shift}: שובץ {tied[0]} (באותו ציון: {', '.join(tied)})"
                )
        result.traces.append(trace)
        if assigned:
            cell = assigned[0]
            if len(assigned) > 1:
                cell += ", " + ", ".join(assigned[1:])
            result.entries[day][shift] = cell

    # if greedy left slots unfilled, attempt exact solvers for a completeness
    if result.unfilled and not _impossible_by_capacity(
        workers, days, shift_names, required_counts, rest_gap
    ):
        greedy_coverage = count_assignments(result.entries)
        greedy_tries = honored_tries(state)
        attempt = _cpsat_exact_cover(
            workers, days, shift_names, required_counts,
            rest_rule, rest_gap, global_rules,
        )
        replaced = False
        if attempt is not None and (
            attempt["coverage"], attempt["tries"]
        ) > (greedy_coverage, greedy_tries):
            result.entries = attempt["entries"]
            result.warnings = []
            result.unfilled = []
            state = attempt["state"]
            replaced = True
            rebuild_unfilled(result.entries)
            if attempt["full"]:
                result.traces.append({"stage": "cpsat", "complete": True})
            else:
                result.traces.append({"stage": "cpsat", "complete": False,
                                      "coverage": attempt["coverage"],
                                      "demand": attempt["demand"]})
                result.warnings.append(
                    f"לא ניתן למלא את כל הדרישות: המקסימום האפשרי לפי הכללים הוא "
                    f"{attempt['coverage']} מתוך {attempt['demand']} "
                    "(מגבלות זמינות, הפסקה ומקסימומים)"
                )
        if not replaced:
            fixed = _exact_cover_search(
                workers, days, shift_names, required_counts,
                rest_rule, rest_gap, rest_soft, candidates_for,
                slots_order=try_slots + other_slots,
            )
            result.traces.append(fixed["trace"])
            fixed_coverage = count_assignments(fixed["entries"])
            if (fixed_coverage, fixed["tries"]) > (greedy_coverage, greedy_tries):
                result.entries = fixed["entries"]
                result.unfilled = []
                if not fixed["complete"]:
                    rebuild_unfilled(result.entries)
                result.warnings = []
                state = fixed["state"]
            else:
                result.warnings.append(
                    "החיפוש הרחב לא מצא שיבוץ חוקי טוב מהנוכחי "
                    f"({fixed['steps']} בדיקות, עדיפויות מומשו: {fixed['tries']}) "
                    "– נשאר הסידור הנוכחי"
                )

    result.warnings.extend(_post_warnings(workers, state, days, shift_names))
    result.state = dict(state)
    _warn_soft_violations(result, workers, state, days, shift_names,
                          rest_rule, rest_gap)

    # note unmet "try" cell preferences (coverage outranks preferences)
    for w in workers:
        for day, cells in w.cell_priority.items():
            for shift in cells:
                if day not in days or shift not in shift_names:
                    continue
                order = days.index(day) * len(shift_names) + shift_names.index(shift)
                if order not in state[w.name].orders:
                    result.warnings.append(
                        f"{w.name}: עדיפות \"נסה לשבץ\" ביום {day} ({shift}) "
                        "לא מומשה"
                    )
    return result


def _post_warnings(
    workers: list[Worker],
    state: dict[str, _WorkerState],
    days: list[str],
    shift_names: list[str],
) -> list[str]:
    warnings: list[str] = []
    for w in workers:
        st = state[w.name]
        r_min = _worker_rule(w, "min_week_shifts")
        if r_min is not None:
            n = int(r_min.params.get("n", 0))
            if len(st.orders) < n:
                warnings.append(
                    f"{w.name}: שובצו {len(st.orders)} משמרות (מינימום {n})"
                )
    return warnings


def _warn_soft_violations(
    result: SolverResult,
    workers: list[Worker],
    state: dict[str, _WorkerState],
    days: list[str],
    shift_names: list[str],
    rest_rule: Rule | None,
    rest_gap: int | None,
) -> None:
    if rest_rule is not None and rest_rule.priority != MUST and rest_gap:
        for w in workers:
            ordered = sorted(state[w.name].orders)
            for a, b in zip(ordered, ordered[1:]):
                if b - a < rest_gap:
                    result.warnings.append(
                        f"{w.name}: מרווח קטן מהמבוקש בין שתי משמרות"
                    )
                    break
    for w in workers:
        r_max_shifts = _worker_rule(w, "max_week_shifts")
        if r_max_shifts is not None and r_max_shifts.priority != MUST:
            n = int(r_max_shifts.params.get("n", 0))
            if len(state[w.name].orders) > n:
                result.warnings.append(
                    f"{w.name}: שובצו יותר מדי משמרות ({len(state[w.name].orders)} > {n})"
                )
        r_max_days = _worker_rule(w, "max_week_days")
        if r_max_days is not None and r_max_days.priority != MUST:
            n = int(r_max_days.params.get("n", 0))
            if len(state[w.name].days) > n:
                result.warnings.append(
                    f"{w.name}: שובצו יותר מדי ימים ({len(state[w.name].days)} > {n})"
                )


def _exact_cover_search(
    workers: list[Worker],
    days: list[str],
    shift_names: list[str],
    required_counts: dict[str, int],
    rest_rule: Rule | None,
    rest_gap: int | None,
    rest_soft: bool,
    candidates_for,
    slots_order: list[tuple[int, int]] | None = None,
) -> dict:
    """Bounded DFS for a better-covered schedule using the same rule engine.

    Returns {"complete": bool, "entries": dict, "state": dict, "steps": int,
    "tries": int, "trace": dict}. Uses the preference-first slot ordering
    when one is supplied.
    """
    slots_seq = slots_order or sorted(
        ((di, si) for di in range(len(days)) for si in range(len(shift_names))),
        key=lambda t: (t[1], t[0]),  # shift-major
    )
    st: dict[str, _WorkerState] = {w.name: _WorkerState() for w in workers}
    entries: dict[str, dict[str, str]] = {d: {} for d in days}
    deadline = _time.monotonic() + SEARCH_BUDGET_SECONDS
    steps = 0
    timed_out = False

    num_slots = len(days) * len(shift_names)
    caps: dict[str, int | None] = {
        w.name: _per_worker_cap(w, num_slots, rest_gap) for w in workers
    }

    def assign(idx: int) -> bool:
        nonlocal steps, timed_out
        if _time.monotonic() > deadline:
            timed_out = True
            return False
        if idx == len(slots_seq):
            return True
        di, si = slots_seq[idx]
        day, shift = days[di], shift_names[si]
        order = di * len(shift_names) + si
        need = required_counts[shift]

        def pick(k: int, taken: frozenset, assigned: list[str]) -> bool:
            nonlocal steps, timed_out
            steps += 1
            if _time.monotonic() > deadline:
                timed_out = True
                return False
            if k == need:
                return assign(idx + 1)
            cands, _rej = candidates_for(day, shift, order, st)
            pool = [(sc, nm) for sc, nm in cands if nm not in taken]
            pool.sort(key=lambda t: (-t[0], t[1]))
            # remaining capacity prune: can anyone still legally cover the rest?
            remaining = sum(
                required_counts[shift_names[dsi[1]]] for dsi in slots_seq[idx:]
            )
            avail = sum(
                max(0, (caps[w.name] if caps[w.name] is not None else num_slots)
                    - len(st[w.name].orders))
                for w in workers
            )
            if avail < remaining:
                return False
            for sc, nm in pool[:SEARCH_CANDIDATE_BRANCH_LIMIT]:
                st[nm].orders.append(order)
                st[nm].days.add(day)
                assigned.append(nm)
                if pick(k + 1, taken | {nm}, assigned):
                    return True
                assigned.pop()
                st[nm].orders.pop()
                if not any((o // len(shift_names)) == di for o in st[nm].orders):
                    st[nm].days.discard(day)
            return False

        return pick(0, frozenset(), [])

    start = _time.monotonic()
    try:
        complete = assign(0)
    except RecursionError:
        complete = False
    if complete:
        for di, si in slots_seq:
            day, shift = days[di], shift_names[si]
            order = di * len(shift_names) + si
            assigned = sorted(
                nm for nm, wst in st.items() if order in wst.orders
            )
            if assigned:
                entries[day][shift] = ", ".join(assigned)
    tries = sum(
        1
        for w in workers
        for day, cells in w.cell_priority.items()
        for shift in cells
        if day in days
        and shift in shift_names
        and days.index(day) * len(shift_names) + shift_names.index(shift)
        in st[w.name].orders
    )
    trace = {
        "stage": "search",
        "complete": complete,
        "steps": steps,
        "tries": tries,
        "timed_out": timed_out,
        "seconds": round(_time.monotonic() - start, 2),
    }
    return {"complete": complete, "entries": entries, "state": st,
            "steps": steps, "tries": tries, "trace": trace}


def explain_slot(
    workers: list[Worker],
    days: list[str],
    shifts: dict[str, str],
    state: dict,
    global_rules: list[Rule] | None,
    day: str,
    shift: str,
) -> list[tuple[str, str]]:
    """For a schedule slot, explain why each worker is/isn't in it.

    Works on the FINAL assignment state (post solver), so the reasons
    reflect the actual schedule rather than the greedy's path.
    """
    if day not in days or shift not in shifts:
        return []
    shift_names = list(shifts)
    order = days.index(day) * len(shift_names) + shift_names.index(shift)
    rest_rule = _global_rule(global_rules or [], "rest_shifts")
    rest_gap = int(rest_rule.params.get("n")) + 1 if rest_rule and rest_rule.params.get("n") else None
    rest_must = bool(rest_rule and rest_rule.priority == MUST)

    out: list[tuple[str, str]] = []
    for w in workers:
        wst = state.get(w.name)
        if wst is None:
            continue
        if order in wst.orders:
            out.append((w.name, "שובץ כאן"))
            continue
        if not w.is_available(day, shift):
            out.append((w.name, "לא זמין במשמרת זו"))
            continue
        r = _worker_rule(w, "max_week_shifts")
        if r is not None and r.priority == MUST and len(wst.orders) >= int(r.params.get("n", 0)):
            out.append((w.name, f"הגיע למקסימום משמרות ({int(r.params.get('n', 0))})"))
            continue
        r_days = _worker_rule(w, "max_week_days")
        if r_days is not None and r.priority == 2 and day not in wst.days and len(wst.days) >= int(r_days.params.get("n", 0)):
            out.append((w.name, f"הגיע למקסימום ימים ({int(r_days.params.get('n', 0))})"))
            continue
        if rest_gap:
            conflicts = [o for o in wst.orders if abs(o - order) < rest_gap]
            if conflicts:
                if rest_must:
                    o0 = min(conflicts, key=lambda o: abs(o - order))
                    d0 = days[o0 // len(shift_names)]
                    s0 = shift_names[o0 % len(shift_names)]
                    out.append((
                        w.name,
                        f"דרוש זמן הפסקה מתאים – שובץ צמוד ביום {d0} ({s0})",
                    ))
                    continue
                out.append((w.name, "מרווח הפסקה קצר מהמבוקש (כלל try)"))
                continue
        out.append((w.name, "פנוי וזמין – לא נבחר על פי כיסוי/העדפות"))
    return out
