import asyncio
import os

from scripts.changed.repo import get_repo
from scripts.helpers.event import get_event

async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-owner")
    repo = get_repo()
    event = get_event()
    actor = event["pull_request"]["user"]["login"]

    if repo.split("/")[0] == event["pull_request"]["user"]["login"]:
        print(f"{actor} is the owner of the repository")
        return

    exit(78)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
