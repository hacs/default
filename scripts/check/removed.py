import asyncio
import os
import requests

CHECKURL = "https://data-v2.hacs.xyz/removed/repositories.json"


async def check():
    repo = os.environ["REPOSITORY"].lower()

    try:
        removed_repositories = set(x.lower() for x in requests.get(CHECKURL).json())
        if repo in removed_repositories:
            exit(f"::error::'{repo}' has been removed from HACS")
    except Exception as e:
        exit(f"::error::{e}")

    print("Repository not removed from HACS")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
