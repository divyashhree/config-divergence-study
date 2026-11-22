"""
GitHub repository discovery and eligibility assessment.

Discovers candidate Kubernetes repositories using GitHub search
and evaluates them for inclusion in the study.

Requirements:
- GitHub API access (personal access token recommended)
- Rate limit respect (1 req/sec default)
- Resumable collection
- Transparent eligibility decisions
"""
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.utils.logging_config import get_logger

logger = get_logger("github_search")

GITHUB_API = "https://api.github.com"


class GitHubSearchError(Exception):
    """Raised when GitHub API request fails."""
    pass


def search_repositories(
    queries: list[str],
    token: str | None = None,
    max_results_per_query: int = 100,
    min_stars: int = 5,
    rate_limit_pause: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Search GitHub for candidate repositories using code search.

    Args:
        queries: GitHub search queries (e.g., 'filename:values-prod.yaml language:YAML').
        token: GitHub personal access token (optional but recommended).
        max_results_per_query: Maximum results per query.
        min_stars: Minimum star count filter.
        rate_limit_pause: Seconds between requests.

    Returns:
        List of candidate repository dicts with metadata.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    all_repos = {}  # Deduplicate by full_name

    for query in queries:
        logger.info(f"Searching: {query}")
        page = 1
        collected = 0

        while collected < max_results_per_query:
            params = {
                "q": query,
                "per_page": min(30, max_results_per_query - collected),
                "page": page,
            }

            try:
                resp = requests.get(
                    f"{GITHUB_API}/search/code",
                    headers=headers,
                    params=params,
                    timeout=30,
                )

                # Handle rate limiting
                if resp.status_code == 403:
                    reset_time = resp.headers.get("X-RateLimit-Reset")
                    if reset_time:
                        wait = max(int(reset_time) - time.time(), 0) + 1
                        logger.warning(f"Rate limited. Waiting {wait}s...")
                        time.sleep(min(wait, 120))
                        continue
                    raise GitHubSearchError(f"GitHub API forbidden: {resp.text}")

                if resp.status_code == 422:
                    logger.warning(f"Query validation error for '{query}': {resp.text}")
                    break

                resp.raise_for_status()
                data = resp.json()

                items = data.get("items", [])
                if not items:
                    break

                for item in items:
                    repo = item.get("repository", {})
                    full_name = repo.get("full_name", "")
                    if full_name and full_name not in all_repos:
                        all_repos[full_name] = {
                            "repo_id": full_name,
                            "url": repo.get("html_url", ""),
                            "description": repo.get("description", ""),
                            "private": repo.get("private", False),
                            "found_via_query": query,
                            "found_file": item.get("path", ""),
                        }
                        collected += 1

                page += 1
                time.sleep(rate_limit_pause)

            except requests.RequestException as e:
                logger.error(f"GitHub API error: {e}")
                break

        logger.info(f"  Found {collected} unique repos for query")

    logger.info(f"Total unique candidates: {len(all_repos)}")
    return list(all_repos.values())


def enrich_repository_metadata(
    candidates: list[dict[str, Any]],
    token: str | None = None,
    rate_limit_pause: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Fetch detailed metadata for each candidate repository.

    Adds: stars, forks, language, created_at, pushed_at, size, etc.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    enriched = []
    for i, candidate in enumerate(candidates):
        repo_id = candidate["repo_id"]
        logger.info(f"Enriching {i+1}/{len(candidates)}: {repo_id}")

        try:
            resp = requests.get(
                f"{GITHUB_API}/repos/{repo_id}",
                headers=headers,
                timeout=30,
            )

            if resp.status_code == 403:
                logger.warning(f"Rate limited on {repo_id}, pausing...")
                time.sleep(60)
                continue

            if resp.status_code == 404:
                logger.warning(f"Repository not found: {repo_id}")
                continue

            resp.raise_for_status()
            data = resp.json()

            candidate.update({
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "language": data.get("language", ""),
                "created_at": data.get("created_at", ""),
                "pushed_at": data.get("pushed_at", ""),
                "size_kb": data.get("size", 0),
                "open_issues": data.get("open_issues_count", 0),
                "default_branch": data.get("default_branch", "main"),
                "license": (data.get("license") or {}).get("spdx_id", ""),
                "archived": data.get("archived", False),
                "fork": data.get("fork", False),
            })
            enriched.append(candidate)
            time.sleep(rate_limit_pause)

        except requests.RequestException as e:
            logger.error(f"Failed to enrich {repo_id}: {e}")
            candidate["enrichment_error"] = str(e)
            enriched.append(candidate)

    return enriched


def save_candidates(
    candidates: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Save candidate list as JSON for resumable processing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "total_candidates": len(candidates),
            "candidates": candidates,
        }, f, indent=2, default=str)
    logger.info(f"Saved {len(candidates)} candidates to {output_path}")


def load_candidates(input_path: Path) -> list[dict[str, Any]]:
    """Load previously saved candidates."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("candidates", [])
