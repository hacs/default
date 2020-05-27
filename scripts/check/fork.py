import asyncio
import json
import os
from glob import glob

from aiogithubapi import GitHub
from scripts.changed.repo import get_repo

TOKEN = os.getenv("GITHUB_TOKEN")


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-fork")
    repo = get_repo()
    async with GitHub(TOKEN) as github:
        repository = await github.get_repo(repo)
        repo = repository.attributes

    if repo["fork"]:
        exit(78)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
