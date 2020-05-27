import asyncio
import json
import os
from glob import glob

from aiogithubapi import GitHub
from scripts.changed.repo import get_repo

TOKEN = os.getenv("GITHUB_TOKEN")
ACTOR = os.getenv("GITHUB_ACTOR")


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-owner")
    repo = get_repo()
    async with GitHub(TOKEN) as github:
        repository = await github.get_repo(repo)
        repo = repository.attributes

    return
    # Currently broken. can not use ACTOR

    if ACTOR == repo["full_name"].split("/")[0]:
        print(f"{ACTOR} is the owner of the repository")
        return

    exit(78)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
