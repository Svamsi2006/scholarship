"""Smoke test – runs the full flow headless on fixture profiles and prints performance report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.events import EventBus
from app.flow import run_flow
from app.models import StudentProfile
from scripts.perf_report import generate_perf_report


def load_profile(name: str) -> dict:
    if not name.endswith(".json"):
        name += ".json"
    fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / name
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return data


def run_smoke(profile_name: str, chaos: bool = False) -> dict:
    print(f"\n{'='*60}")
    print(f"SMOKE RUN: {profile_name} (Chaos: {chaos})")
    print(f"{'='*60}")

    data = load_profile(profile_name)
    profile = StudentProfile.model_validate(data)

    bus = EventBus()

    # Build form fields from fixture
    form_fields = {
        "name": profile.name,
        "target_level": profile.target_level,
        "target_fields": profile.target_fields,
        "target_countries": profile.target_countries,
        "funding_need": profile.funding_need,
    }

    # Build resume text from fixture
    resume_parts = [f"Name: {profile.name}"]
    for edu in profile.education:
        resume_parts.append(
            f"Education: {edu.degree} in {edu.field} from {edu.institution}, CGPA: {edu.cgpa}/{edu.cgpa_scale}"
        )
    resume_parts.append(f"Skills: {', '.join(profile.skills)}")
    for proj in profile.projects:
        resume_parts.append(f"Project: {proj.name} - {proj.description}")
    for ach in profile.achievements:
        resume_parts.append(f"Achievement: {ach}")
    resume_text = "\n".join(resume_parts)

    github_url = profile.github.profile_url if profile.github else ""

    result = run_flow(
        resume_text=resume_text,
        github_url=github_url,
        form_fields=form_fields,
        bus=bus,
        chaos=chaos,
    )

    # Print results summary
    print("\n--- RESULTS SUMMARY ---")
    print(f"Profile: {result.profile.name}")
    print(f"Rounds used: {result.rounds_used}")
    print(f"All checked: {len(result.all_checked)}")
    print(f"Ranked: {len(result.ranked)}")

    print("\n--- TOP RECOMMENDATIONS ---")
    for r in result.ranked:
        opp = r.opportunity
        verified_mark = "[VERIFIED]" if opp.status == "verified" else "[PARTIAL]"
        print(f"  #{r.rank} {verified_mark} {opp.candidate.name}")
        print(f"     URL: {opp.official_url or opp.candidate.source_url}")
        print(f"     Deadline: {opp.deadline.value} ({opp.deadline_state}) | quote_verified={opp.deadline.verified}")
        print(f"     Funding: {opp.funding.value} | quote_verified={opp.funding.verified}")
        print(f"     Why Fit: {r.why_fit[:120]}")
        print()

    # Verification integrity check
    print("\n--- VERIFICATION INTEGRITY CHECK ---")
    all_pass = True
    for r in result.ranked:
        opp = r.opportunity
        for field_name in ("deadline", "funding"):
            evidenced = getattr(opp, field_name)
            if evidenced.value and not evidenced.verified:
                print(f"  [WARN] {opp.candidate.name}.{field_name} has value but unverified quote")
                all_pass = False

    if all_pass:
        print("  PASS: All displayed values strictly evidence-backed")
    else:
        print("  INFO: Some fields marked unverified according to policy")

    if result.sop:
        print("\n--- SOP DRAFT ---")
        print(f"  Target: {result.sop.target_name}")
        print(f"  Length: {len(result.sop.text)} chars")
        print(f"  Facts used: {len(result.sop.facts_used)}")
        print(f"  Placeholders: {len(result.sop.placeholders)}")

    # Run performance report
    perf_data = generate_perf_report(bus.run_id)
    return perf_data


if __name__ == "__main__":
    profiles = sys.argv[1:] if len(sys.argv) > 1 else ["profile_a.json"]
    for pname in profiles:
        run_smoke(pname)
