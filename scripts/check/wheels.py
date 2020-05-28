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
    print("Information: https://hacs.xyz/docs/publish/include#check-wheels")
    if get_category() != "integration":
        print("Only integrations are checked.")
        return

    manifest = get_manifest()

    domain = manifest.get("domain")
    requirements = manifest.get("requirements")
    if domain is None:
        exit("No domain")

    if not requirements:
        print("No requirements found")
        return

    async with GitHub(TOKEN) as github:
        repository = await github.get_repo("home-assistant/wheels-custom-integrations")
        files = await repository.get_contents("components")
        components = [x.attributes["name"] for x in files]
        if domain in components or f"{domain}.json" in components:
            print(
                f"{domain} is added to https://github.com/home-assistant/wheels-custom-integrations, NICE!"
            )
            return
        exit(
            f"::error::{domain} is not added to https://github.com/home-assistant/wheels-custom-integrations, "
            + "this is needed to ensure the best possible experience for the user"
        )


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
