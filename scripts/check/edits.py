import asyncio

from scripts.helpers.event import get_event


async def check():
    event = get_event()
    pull_request = event["pull_request"]
    if not pull_request["maintainer_can_modify"]:
        if pull_request["head"]["repo"]["full_name"] != "hacs/default":
            exit("::error::The PR is not editable by HACS maintainers")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
