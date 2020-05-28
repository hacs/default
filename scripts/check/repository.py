import asyncio
import json
import os
from glob import glob

from aiogithubapi import GitHub
from scripts.changed.repo import get_repo

TOKEN = os.getenv("GITHUB_TOKEN")


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-repository")
    repo = get_repo()
    issues = []
    async with GitHub(TOKEN) as github:
        repository = await github.get_repo(repo)
        repo = repository.attributes

    if not repo["has_issues"]:
        issues.append("::error::Issues not enabled.")

    if not repo["description"]:
        issues.append(
            "::error::No description. (https://hacs.xyz/docs/publish/start#description)"
        )

    if not repo["topics"]:
        issues.append("::error::No topics. (https://hacs.xyz/docs/publish/start#topics)")

    if issues:
        for issue in issues:
            print(issue)
        exit(1)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
