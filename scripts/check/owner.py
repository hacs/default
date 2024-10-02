import asyncio
import os

from scripts.helpers.event import get_event
from scripts.remove_publishers import REMOVED_PUBLISHERS
from aiogithubapi import GitHub, AIOGitHubAPIException

TOKEN = os.getenv("GITHUB_TOKEN")


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-owner")
    repo = os.environ["REPOSITORY"]
    event = get_event()
    actor = event["pull_request"]["user"]["login"]
    repo_owner = repo.split("/")[0].lower()

    for removed in REMOVED_PUBLISHERS:
        if repo_owner == removed["publisher"].lower():
            exit(
                f"::error::'{repo_owner}' is not allowed to publish default repositories"
            )

    if repo_owner == actor.lower():
        print(f"'{actor}' is the owner of '{repo}'")
        return

    try:
        async with GitHub(TOKEN) as github:
            request = await github.client.get(
                f"/repos/{repo}/contributors",
                headers={},
            )
            contributors = [
                {"login": x["login"], "contributions": x["contributions"]}
                for x in request.data or []
            ]
            _sorted = sorted(
                contributors, key=lambda x: x["contributions"], reverse=True
            )

            _top = _sorted[0]["contributions"]

            if actor not in [x["login"] for x in _sorted]:
                exit(f"::error::'{actor}' is not a contributor to '{repo}'")

            if [x["contributions"] for x in _sorted if x["login"] == actor].pop() >= (
                _top / 3
            ):
                print(f"'{actor}' is a major contributor to '{repo}'")
                return
    except AIOGitHubAPIException as e:
        exit(f"::error::{e}")

    exit(f"::error::'{actor}' is not a major contributor to '{repo}'")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
