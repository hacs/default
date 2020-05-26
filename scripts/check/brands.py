import asyncio
import json
import os
from glob import glob

from aiogithubapi import GitHub
from scripts.changed.category import get_category
from scripts.changed.repo import get_repo
from scripts.helpers.manifest import get_manifest

TOKEN = os.getenv("GITHUB_TOKEN")


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-brands")
    if get_category() != "integration":
        print("Only integrations are checked.")
        return

    manifest = get_manifest()

    domain = manifest.get("domain")
    if domain is None:
        print("No domain")
        exit(1)

    async with GitHub(TOKEN) as github:
        repository = await github.get_repo("home-assistant/brands")
        files = await repository.get_contents("custom_integrations")
        if domain not in [x.attributes["name"] for x in files]:
            print(f"{domain} is not added to https://github.com/home-assistant/brands")
            print("This is needed to ensure the best possible experience for the user")
            exit(1)
        else:
            print(
                f"{domain} is added to https://github.com/home-assistant/brands, NICE!"
            )


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
