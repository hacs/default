import asyncio
import os

from aiogithubapi import GitHub, AIOGitHubAPIException

TOKEN = os.getenv("GITHUB_TOKEN")


async def check():
    repo = os.environ["REPOSITORY"]
    print("Information: https://hacs.xyz/docs/publish/include#check-releases")
    try:
        async with GitHub(TOKEN) as github:
            request = await github.client.get(f"/repos/{repo}/releases", headers={})
            if isinstance(request.data, list) and len(request.data) > 0:
                print(f"'{repo}' has releases")
                return

    except AIOGitHubAPIException as e:
        print(f"::error::{e}")
        exit(f"::error::{e}")

    exit(f"::error::'{repo}' has no releases")

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
