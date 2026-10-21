"""Adaptability tests – no hardcoded names, profiles produce different results."""

import json
import re
from pathlib import Path

from app.models import StudentProfile
from app.tasks import research_prompt

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_profile(name: str) -> StudentProfile:
    path = FIXTURES_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    return StudentProfile.model_validate(data)


def test_profiles_produce_different_queries():
    """Research queries for profile A and B should differ materially."""
    profile_a = _load_profile("profile_a.json")
    profile_b = _load_profile("profile_b.json")

    prompt_a = research_prompt(profile_a, 1, [], [], "")
    prompt_b = research_prompt(profile_b, 1, [], [], "")

    # Prompts should differ – different fields, countries, etc.
    assert prompt_a != prompt_b
    assert "Computer Science" in prompt_a or "Artificial Intelligence" in prompt_a
    assert "Biotechnology" in prompt_b or "Bioinformatics" in prompt_b
    assert "USA" in prompt_a or "UK" in prompt_a
    assert "Germany" in prompt_b or "Netherlands" in prompt_b


def test_no_hardcoded_student_names_in_app_code():
    """No product code under app/ should contain hardcoded student names."""
    app_dir = Path(__file__).parent.parent / "app"
    forbidden = ["Rahul", "Priya", "Kumar", "Sharma"]

    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for name in forbidden:
            # Allow in comments and strings that are clearly test/doc related
            lines = content.split("\n")
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if name in stripped:
                    assert False, (
                        f"Hardcoded name '{name}' found in {py_file}:{line_num}: {stripped}"
                    )


def test_no_hardcoded_scholarship_names_in_app_code():
    """No product code should contain hardcoded scholarship names."""
    app_dir = Path(__file__).parent.parent / "app"
    # Common scholarship names that might get accidentally hardcoded
    forbidden_patterns = [
        r"Fulbright",
        r"Chevening",
        r"DAAD",
        r"Commonwealth",
        r"Rhodes",
    ]

    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            for line_num, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(pattern, stripped):
                    assert False, (
                        f"Hardcoded scholarship '{pattern}' found in {py_file}:{line_num}: {stripped}"
                    )


def test_profile_without_github_works():
    """Profile B has no GitHub – should still produce valid prompts."""
    profile_b = _load_profile("profile_b.json")
    assert profile_b.github is None

    prompt = research_prompt(profile_b, 1, [], [], "")
    assert "Has GitHub: no" in prompt
