import json
from scripts.changed.category import get_category

DEFAULT = "/tmp/repositories/default"


def get_repo():
    category = get_category()
    with open(f"{DEFAULT}/{category}", "r") as default:
        current = json.loads(default.read())

    with open(category, "r") as default:
        new = json.loads(default.read())

    for repo in current:
        if repo in new:
            new.remove(repo)

    if len(new) != 1:
        print(f"Bad data {new}")
        exit(1)

    return new.pop()


if __name__ == "__main__":
    print(get_repo())
