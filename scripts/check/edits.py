import asyncio

from scripts.helpers.event import get_event


async def check():

    event = get_event()
    pull_request = event["pull_request"]
    print(pull_request)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
