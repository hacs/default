import asyncio
import os
import requests

CATEGORIES = [
    "appdaemon",
    "integration",
    "netdaemon",
    "plugin",
    "python_script",
    "template",
    "theme",
]


async def check():
    repo = os.environ["REPOSITORY"].lower()

    for category in CATEGORIES:
        checkurl = f"https://data-v2.hacs.xyz/{category}/repositories.json"
        try:
            category_repositories = set(x.lower() for x in requests.get(checkurl).json())
            if repo in category_repositories:
                exit(f"::error::'{repo}' alredy exist as a {category} in HACS")
        except Exception as e:
            exit(f"::error::{e}")

    print("Repository does not exist in HACS")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
