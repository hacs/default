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

    if repo.split("/")[0] == actor:
        print(f"'{actor}' is the owner of '{repo}'")
        return

    try:
        async with GitHub(TOKEN) as github:
            request = await github.client.get(
                f"/repos/{repo}/contributors", headers={},
            )
            contributors = [
                {"login": x["login"], "contributions": x["contributions"]}
                for x in request or []
            ]
            _sorted = sorted(
                contributors, key=lambda x: x["contributions"], reverse=True
            )

            _top = _sorted[0]["contributions"]

            if actor not in [x["login"] for x in _sorted]:
                exit(f"::error::'{actor}' is not a contributor to '{repo}'")

            if [x["contributions"] for x in _sorted if x["login"] == actor].pop() > (
                _top / 2
            ):
                print(f"'{actor}' is a major contributor to '{repo}'")
                return
    except AIOGitHubAPIException as e:
        exit(f"::error::{e}")

    exit(f"::error::'{actor}' is not a major contributor to '{repo}'")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
