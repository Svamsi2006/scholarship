"""github_profile – complete pagination, weighted language aggregation, and parallel notable repo analysis."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import GITHUB_TOKEN
from app.events import EventBus, global_bus

_API = "https://api.github.com"


def _headers() -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ScholarshipStar-Researcher/2.0",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _signal_score(repo: dict[str, Any]) -> float:
    """Compute ranking score for notable repos based on stars, description, recency."""
    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    is_fork = repo.get("fork", False)
    has_desc = bool(repo.get("description"))

    score = (stars * 5.0) + (forks * 2.0)
    if has_desc:
        score += 10.0
    if not is_fork:
        score += 15.0

    pushed_at = repo.get("pushed_at")
    if pushed_at:
        try:
            dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            days_ago = (datetime.now(UTC) - dt).days
            if days_ago < 30:
                score += 20.0
            elif days_ago < 180:
                score += 10.0
            elif days_ago < 365:
                score += 5.0
        except Exception:
            pass

    return score


async def _fetch_repo_details(client: httpx.AsyncClient, username: str, repo: dict[str, Any]) -> dict[str, Any]:
    """Fetch README and detailed languages for a notable repo in parallel."""
    repo_name = repo.get("name", "")
    desc = repo.get("description") or ""
    primary_lang = repo.get("language")
    languages = [primary_lang] if primary_lang else []

    # 1. Fetch languages
    langs_url = repo.get("languages_url")
    if langs_url:
        try:
            resp = await client.get(langs_url)
            if resp.status_code == 200:
                languages = list(resp.json().keys())
        except Exception:
            pass

    # 2. Fetch README
    readme_snippet = ""
    try:
        readme_resp = await client.get(
            f"{_API}/repos/{username}/{repo_name}/readme",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if readme_resp.status_code == 200:
            readme_text = readme_resp.text.strip()
            readme_snippet = readme_text[:500]
            if not desc and readme_snippet:
                desc = readme_snippet[:200].replace("\n", " ")
    except Exception:
        pass

    return {
        "name": repo_name,
        "description": desc,
        "tech": languages,
        "url": repo.get("html_url", f"https://github.com/{username}/{repo_name}"),
        "stars": repo.get("stargazers_count", 0),
        "readme_snippet": readme_snippet,
    }


async def github_profile_async(
    username_or_url: str,
    bus: EventBus | None = None,
    agent: str = "ProfileAnalyst",
    run_id: str = "",
) -> dict[str, Any]:
    """Fetch full GitHub user profile with complete repo pagination and parallel detail fetching."""
    event_bus = bus or global_bus

    # Parse username from URL or raw string
    username = username_or_url.strip().rstrip("/")
    if "github.com/" in username:
        username = username.split("github.com/")[-1].split("/")[0]
    username = username.lstrip("@")

    if not username:
        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent,
                "type": "warning",
                "phase": "profile",
                "message": "No GitHub username provided",
            }
        )
        return {"error": "No GitHub username provided"}

    event_bus.emit(
        {
            "run_id": run_id,
            "agent": agent,
            "type": "tool_call",
            "phase": "profile",
            "message": f"Fetching full GitHub profile for {username}",
            "data": {"username": username},
        }
    )

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_headers()) as client:
            user_resp = await client.get(f"{_API}/users/{username}")
            if user_resp.status_code == 404:
                event_bus.emit(
                    {
                        "run_id": run_id,
                        "agent": agent,
                        "type": "warning",
                        "phase": "profile",
                        "message": f"GitHub user {username} not found (404)",
                    }
                )
                return {"error": f"User {username} not found"}
            if user_resp.status_code == 403:
                event_bus.emit(
                    {
                        "run_id": run_id,
                        "agent": agent,
                        "type": "warning",
                        "phase": "profile",
                        "message": "GitHub API rate limit exceeded",
                    }
                )
                return {"error": "GitHub rate limit exceeded"}

            user_resp.raise_for_status()
            user_data = user_resp.json()

            # Paginate through all public repos
            all_repos: list[dict[str, Any]] = []
            page = 1
            while True:
                repos_resp = await client.get(
                    f"{_API}/users/{username}/repos",
                    params={
                        "per_page": 100,
                        "type": "owner",
                        "sort": "pushed",
                        "page": page,
                    },
                )
                if repos_resp.status_code != 200:
                    break
                page_data = repos_resp.json()
                if not page_data or not isinstance(page_data, list):
                    break
                all_repos.extend(page_data)
                if len(page_data) < 100:
                    break
                page += 1

            total_repos = len(all_repos)
            true_public_count = user_data.get("public_repos", total_repos)
            effective_total = max(total_repos, true_public_count)

            # Aggregate languages across all repos (weighted by stars and non-fork)
            lang_counts: dict[str, float] = {}
            fork_count = 0
            for r in all_repos:
                is_fork = r.get("fork", False)
                if is_fork:
                    fork_count += 1
                lang = r.get("language")
                if lang:
                    weight = 1.0 + (r.get("stargazers_count", 0) * 0.5)
                    if not is_fork:
                        weight += 1.0
                    lang_counts[lang] = lang_counts.get(lang, 0.0) + weight

            sorted_langs = [
                lang for lang, _ in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            # Rank repos by signal score and pick top 8 notable
            ranked_repos = sorted(all_repos, key=_signal_score, reverse=True)
            top_notable = ranked_repos[:8]

            # Fetch details (README + languages) for top 8 in parallel
            fetch_tasks = [_fetch_repo_details(client, username, r) for r in top_notable]
            notable_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            notable: list[dict[str, Any]] = []
            for item in notable_results:
                if isinstance(item, dict):
                    notable.append(item)

            summary_text = (
                f"Analyzed {len(notable)} of {effective_total} repos (top by signal); "
                f"{effective_total} public repos total ({fork_count} forks); "
                f"languages: {', '.join(sorted_langs[:6]) if sorted_langs else 'None'}"
            )

            result = {
                "username": username,
                "profile_url": f"https://github.com/{username}",
                "top_languages": sorted_langs,
                "notable_repos": notable,
                "public_repo_count": effective_total,
                "fork_repo_count": fork_count,
                "summary_text": summary_text,
            }

            event_bus.emit(
                {
                    "run_id": run_id,
                    "agent": agent,
                    "type": "tool_result",
                    "phase": "profile",
                    "message": f"GitHub: {summary_text}",
                    "data": {
                        "username": username,
                        "total_repos": effective_total,
                        "languages": sorted_langs,
                        "notable_count": len(notable),
                    },
                }
            )
            return result

    except Exception as exc:
        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent,
                "type": "warning",
                "phase": "profile",
                "message": f"GitHub API error: {exc}",
            }
        )
        return {"error": str(exc)}


def github_profile(
    username_or_url: str,
    bus: EventBus | None = None,
    agent: str = "ProfileAnalyst",
    run_id: str = "",
) -> dict[str, Any]:
    """Synchronous wrapper for github_profile_async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run, github_profile_async(username_or_url, bus=bus, agent=agent, run_id=run_id)
                )
                return future.result(timeout=20)
        else:
            return loop.run_until_complete(
                github_profile_async(username_or_url, bus=bus, agent=agent, run_id=run_id)
            )
    except Exception:
        return asyncio.run(
            github_profile_async(username_or_url, bus=bus, agent=agent, run_id=run_id)
        )
