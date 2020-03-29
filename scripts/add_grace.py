import sys
import json
from datetime import datetime, timedelta


def add_grace(repo):
    until = datetime.now() + timedelta(days=60)
    with open("grace.json", "r") as grace_file:
        grace = json.loads(grace_file.read())

    if grace.get(repo) is not None:
        grace[repo] = {"until": until.timestamp(), "count": grace[repo]["count"] + 1}
    else:
        grace[repo] = {"until": until.timestamp(), "count": 1}

    with open("grace.json", "w") as grace_file:
        grace_file.write(json.dumps(grace, indent=2))


if __name__ == "__main__":
    try:
        repo = sys.argv[1]
        add_grace(repo)
    except IndexError:
        print("No valid repository")
