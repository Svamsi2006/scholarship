"""Tests for github_profile – pagination, language aggregation, and notable repo signal scoring."""

from unittest.mock import patch

import pytest

from app.events import EventBus
from app.tools.github import github_profile_async


def _generate_mock_repos(count: int = 25):
    repos = []
    languages = ["Python", "TypeScript", "Rust", "Go", "Java"]
    for i in range(count):
        lang = languages[i % len(languages)]
        repos.append({
            "name": f"repo-{i+1}",
            "stargazers_count": 25 - i,
            "forks_count": i % 3,
            "fork": (i % 5 == 0),  # every 5th is a fork
            "language": lang,
            "description": f"Description for repository {i+1}",
            "languages_url": f"https://api.github.com/repos/testuser/repo-{i+1}/languages",
            "html_url": f"https://github.com/testuser/repo-{i+1}",
            "pushed_at": "2026-10-15T12:00:00Z",
        })
    return repos


@pytest.mark.asyncio
async def test_github_25_repos_coverage():
    """TASK v2 3.5: Mocked GitHub with 25 repos must yield public_repo_count == 25, >= 3 languages, 8 notable."""
    bus = EventBus()
    mock_repos = _generate_mock_repos(25)

    class MockAsyncResponse:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

        def raise_for_status(self):
            pass

    async def mock_get(url, **kwargs):
        if "/users/testuser/repos" in url:
            # Page 1 returns 25 repos
            params = kwargs.get("params", {})
            page = params.get("page", 1)
            if page == 1:
                return MockAsyncResponse(mock_repos)
            return MockAsyncResponse([])
        elif "/users/testuser" in url:
            return MockAsyncResponse({"login": "testuser", "public_repos": 25})
        elif "/readme" in url:
            return MockAsyncResponse("Sample README documentation", status_code=200)
        elif "/languages" in url:
            return MockAsyncResponse({"Python": 1000, "Rust": 500})
        return MockAsyncResponse({}, status_code=404)

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await github_profile_async("testuser", bus=bus)

        assert result["username"] == "testuser"
        assert result["public_repo_count"] == 25
        assert len(result["top_languages"]) >= 3
        assert len(result["notable_repos"]) == 8
        assert "Analyzed 8 of 25 repos" in result["summary_text"]
