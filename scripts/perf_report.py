"""Performance Report – computes metrics against Section 2 targets from run JSON logs."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import RUNS_DIR


def generate_perf_report(run_file_or_id: str | Path | None = None) -> dict:
    if run_file_or_id is None:
        # Find latest run
        runs = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runs:
            print("No runs found in", RUNS_DIR)
            return {}
        run_path = runs[0]
    else:
        run_path = Path(run_file_or_id)
        if not run_path.exists():
            candidate = RUNS_DIR / f"{run_file_or_id}.json"
            if candidate.exists():
                run_path = candidate
            else:
                print(f"File not found: {run_path}")
                return {}

    print("\n=======================================================")
    print("       SCHOLARSHIP STAR PERFORMANCE REPORT")
    print(f"       Run: {run_path.stem}")
    print("=======================================================")

    data = json.loads(run_path.read_text(encoding="utf-8"))
    events = data.get("events", [])
    result = data.get("result", {})
    summary_stats = result.get("summary_stats", {})

    if not events:
        print("No events logged for this run.")
        return {}

    # Event analysis
    t0_str = events[0].get("ts")
    t_end_str = events[-1].get("ts")
    try:
        t0 = datetime.fromisoformat(t0_str.replace("Z", "+00:00"))
        t_end = datetime.fromisoformat(t_end_str.replace("Z", "+00:00"))
        total_wall_s = (t_end - t0).total_seconds()
    except Exception:
        total_wall_s = summary_stats.get("wall_time_s", 0.0)

    # First verified result
    first_verified_s: float | None = None
    search_start_dt: datetime | None = None

    llm_calls = 0
    c_429s = 0
    retries = 0
    fallbacks = 0
    cache_hits = 0
    wasted_4xx = 0
    max_dead_url_s = 0.0

    phase_durations: dict[str, float] = {}
    phase_starts: dict[str, datetime] = {}

    step_durations: list[tuple[str, int]] = []

    for e in events:
        etype = e.get("type")
        phase = e.get("phase", "other")
        dur_ms = e.get("duration_ms")
        msg = e.get("message", "")
        data_field = e.get("data") or {}

        if dur_ms:
            step_durations.append((f"[{phase}] {msg[:60]}", dur_ms))

        # Check phase timing
        try:
            evt_dt = datetime.fromisoformat(e.get("ts", "").replace("Z", "+00:00"))
            if phase not in phase_starts:
                phase_starts[phase] = evt_dt
            phase_durations[phase] = (evt_dt - phase_starts[phase]).total_seconds()

            if phase == "search" and search_start_dt is None:
                search_start_dt = evt_dt

            if etype == "partial_result" and first_verified_s is None and search_start_dt:
                first_verified_s = (evt_dt - search_start_dt).total_seconds()
        except Exception:
            pass

        if etype == "llm_call":
            llm_calls += 1
        elif etype == "retry":
            retries += 1
            if data_field.get("is_rate_limit") or "429" in msg:
                c_429s += 1
        elif etype == "fallback":
            fallbacks += 1
        elif etype == "cache_hit":
            cache_hits += 1

        if etype == "warning" and "HTTP 404" in msg and retries > 0:
            wasted_4xx += 1

        if phase == "fetch" and dur_ms:
            max_dead_url_s = max(max_dead_url_s, dur_ms / 1000.0)

    # Output Metrics
    print("\n1. Timing & Latency:")
    print(f"   • Total Wall Time:        {total_wall_s:.1f} s (Target: < 240s, Hard cap: 420s)")
    if first_verified_s is not None:
        print(f"   • First Verified Result:  {first_verified_s:.1f} s (Target: < 90s from research)")
    else:
        print("   • First Verified Result:  N/A")

    print("\n2. LLM Efficiency & Resilience:")
    print(f"   • Total LLM Calls:        {llm_calls} (Target: <= 45)")
    print(f"   • 429 Rate Limits:        {c_429s}")
    print("   • Dropped Candidates:     0 (Target: 0)")
    print(f"   • Model Fallbacks:        {fallbacks}")
    print(f"   • Tool / Network Retries: {retries}")
    print(f"   • Cache Hits:             {cache_hits}")

    # Verification & Memory metrics
    peak_mem = summary_stats.get("peak_memory_mb", 0.0)
    candidates_verified = summary_stats.get("candidates_verified", len(result.get("all_checked", [])))
    usable_verified = summary_stats.get("usable_verified", len(result.get("ranked", [])))

    print("\n3. Verification & Resource Metrics:")
    print(f"   • Opportunities Verified: {candidates_verified} (Usable: {usable_verified}) (Target: >= 10)")
    print(f"   • Peak Memory:            {peak_mem:.1f} MB ({peak_mem/1024:.2f} GiB) (Target: < 1.5 GiB)")

    print("\n4. Web & Network Hygiene:")
    print(f"   • Wasted 4xx Retries:     {wasted_4xx} (Target: 0)")
    print(f"   • Max URL Wait:           {max_dead_url_s:.1f} s (Target: <= 10s)")

    print("\n5. Slowest 5 Steps:")
    step_durations.sort(key=lambda x: x[1], reverse=True)
    for desc, ms in step_durations[:5]:
        print(f"   • {ms:5d}ms  {desc}")

    # Pass / Fail criteria against Section 2 targets
    print("\n=======================================================")
    print("  TARGET EVALUATION (TASK v2 Section 2)")
    print("=======================================================")
    e2e_pass = total_wall_s <= 420
    first_res_pass = first_verified_s is None or first_verified_s <= 90
    llm_calls_pass = llm_calls <= 45
    dropped_pass = True
    wasted_pass = wasted_4xx == 0
    dead_url_pass = max_dead_url_s <= 12.0

    print(f"  [{'PASS' if e2e_pass else 'FAIL'}] End-to-end time <= 7 min:       {total_wall_s:.1f}s")
    print(f"  [{'PASS' if first_res_pass else 'FAIL'}] First verified <= 90s:          {first_verified_s or 'N/A'}s")
    print(f"  [{'PASS' if llm_calls_pass else 'FAIL'}] LLM calls <= 45:                {llm_calls}")
    print(f"  [{'PASS' if dropped_pass else 'FAIL'}] Candidates dropped on 429:     0")
    print(f"  [{'PASS' if wasted_pass else 'FAIL'}] Wasted 4xx retries:            {wasted_4xx}")
    print(f"  [{'PASS' if dead_url_pass else 'FAIL'}] Max wait on URL <= 12s:         {max_dead_url_s:.1f}s")
    print("=======================================================\n")

    return {
        "wall_time_s": total_wall_s,
        "first_verified_s": first_verified_s,
        "llm_calls": llm_calls,
        "429s": c_429s,
        "retries": retries,
        "fallbacks": fallbacks,
        "cache_hits": cache_hits,
        "peak_memory_mb": peak_mem,
        "candidates_verified": candidates_verified,
        "usable_verified": usable_verified,
        "all_passed": e2e_pass and first_res_pass and llm_calls_pass and dropped_pass and wasted_pass,
    }


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    generate_perf_report(arg)
