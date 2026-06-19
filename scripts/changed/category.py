import json


DEFAULT = "/tmp/repositories/default"

CATEGORIES = [
    "appdaemon",
    "integration",
    "netdaemon",
    "plugin",
    "python_script",
    "template",
    "theme",
]

CURRENT = {}
CHANGED = {}


def get_category():
    for category in CATEGORIES:
        with open(f"{DEFAULT}/{category}", "r") as default:
            CURRENT[category] = json.loads(default.read())

    for category in CATEGORIES:
        with open(category, "r") as default:
            CHANGED[category] = json.loads(default.read())

    for category in CATEGORIES:
        for repo in CURRENT[category]:
            if repo in CHANGED[category]:
                CHANGED[category].remove(repo)

    changed = []
    for category in CATEGORIES:
        if CHANGED[category]:
            changed.append(category)

    if len(changed) != 1:
        print(f"Bad data {changed}")
        exit(1)

    return changed.pop()


if __name__ == "__main__":
    print(get_category())
