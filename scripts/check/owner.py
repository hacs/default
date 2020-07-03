import asyncio
import os

from scripts.changed.repo import get_repo
from scripts.helpers.event import get_event
from aiogithubapi import GitHub, AIOGitHubAPIException

TOKEN = os.getenv("GITHUB_TOKEN")


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-owner")
    repo = get_repo()
    event = get_event()
    actor = event["pull_request"]["user"]["login"]

    try:
        async with GitHub(TOKEN) as github:
            request = await github.client.get(
                endpoint=f"/repos/{repo}/collaborators/{actor}/permission",
                headers=None,
            )

            permission = request.get("permission", "read")

            if permission in ["admin", "write"]:
                print(f"{actor} is the owner of the repository")
                return
    except AIOGitHubAPIException as e:
        exit(f"::error::{e}")

    exit(f"::error::{actor} does not have write access to the repository")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
