import asyncio
import json
import os
from glob import glob

from aiogithubapi import GitHub
from scripts.changed.category import get_category
from scripts.changed.repo import get_repo

TOKEN = os.getenv("GITHUB_TOKEN")

async def check():
    if get_category() != "integration":
        print("Only integrations are checked.")
        return

    files = []
    for dir,_,_ in os.walk("/tmp/addition"):
        files.extend(glob(os.path.join(dir, "*manifest.json")))

    if len(files) != 1:
        print("No manifest")
        exit(1)

    with open(files.pop(), "r") as mf:
        manifest = json.loads(mf.read())

    domain = manifest.get("domain")
    if domain is None:
        print("No domain")
        exit(1)

    async with GitHub(TOKEN) as github:
        repository = await github.get_repo("home-assistant/brands")
        files = await repository.get_contents("custom_integrations")
        if domain not in [x.attributes["name"] for x in files]:
            print(f"{domain} is not added to https://github.com/home-assistant/brands")
            exit(1)
        else:
            print(f"{domain} is added to https://github.com/home-assistant/brands, NICE!" )


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())