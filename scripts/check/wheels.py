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
        repository = await github.get_repo("home-assistant/wheels-custom-integrations")
        files = await repository.get_contents("components")
        components = [x.attributes["name"] for x in files]
        if domain in components or f"{domain}.json" in components:
            print(f"{domain} is added to https://github.com/home-assistant/wheels-custom-integrations, NICE!")
            return
        print(f"{domain} is not added to https://github.com/home-assistant/wheels-custom-integrations")
        exit(1)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())