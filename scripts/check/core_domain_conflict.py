import asyncio
import requests

from scripts.helpers.domain import get_domain

# The next site is built from the upcoming release, so it also lists domains
# that are not shipped yet.
CHECKURL = "https://next.home-assistant.io/integrations.json"


async def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-core-domain-conflict")
    domain = get_domain()
    if not domain:
        exit("::error::The integration manifest has no domain")

    try:
        core_domains = requests.get(CHECKURL, timeout=30).json()
        if domain in core_domains:
            exit(f"::error::'{domain}' is the domain of a Home Assistant core integration")
    except Exception as e:
        exit(f"::error::{e}")

    print(f"'{domain}' is not used by a Home Assistant core integration")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(check())
