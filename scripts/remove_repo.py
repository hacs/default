import sys
import json

# Information https://hacs.xyz/docs/publish/remove

if len(sys.argv) < 3:
    print(
        '  Usage: python3 scripts/remove_repo.py [repository] [removal_type] "[reason]" [link]'
    )
    exit(1)

try:
    repo = sys.argv[1]
except Exception:
    repo = None

try:
    removal_type = sys.argv[2]
except Exception:
    removal_type = None

try:
    reason = sys.argv[3]
except Exception:
    reason = None

try:
    link = sys.argv[4]
except Exception:
    link = None

remove = {
    "link": link,
    "reason": reason,
    "removal_type": removal_type,
    "repository": repo,
}

orgs = ["custom-cards", "custom-components"]

foundcategory = None
categorycontent = None
blacklistcontent = None
removedcontent = None

for category in [
    "appdaemon",
    "integration",
    "netdaemon",
    "plugin",
    "python_script",
    "template",
    "theme",
]:
    with open(category, "r") as cat_file:
        content = json.loads(cat_file.read())
        if remove["repository"] in content:
            print(f"Found in {category}")
            foundcategory = category
            categorycontent = content
            content.remove(remove["repository"])
            with open(category, "w") as outfile:
                outfile.write(json.dumps(sorted(content, key=str.casefold), indent=2))
            break

if remove["repository"].split("/")[0] not in orgs:
    if foundcategory is None or foundcategory is None:
        print(f"Could not find repository {remove['repository']}")
        exit(1)

with open("blacklist", "r") as blacklist_file:
    blacklistcontent = json.loads(blacklist_file.read())

with open("removed", "r") as removed_file:
    removedcontent = json.loads(removed_file.read())

if remove["repository"] in blacklistcontent:
    print(f"{remove['repository']} has already been removed")
    exit(0)

blacklistcontent.append(remove["repository"])

if remove["repository"].split("/")[0] not in orgs:
    if remove["repository"] in categorycontent:
        categorycontent.remove(remove["repository"])

data = {"repository": remove["repository"]}
if remove["reason"] is not None:
    data["reason"] = remove["reason"]
if remove["removal_type"] is not None:
    data["removal_type"] = remove["removal_type"]
if remove["link"] is not None:
    data["link"] = remove["link"]

removedcontent.append(data)

with open("blacklist", "w") as blacklist_file:
    blacklist_file.write(
        json.dumps(sorted(blacklistcontent, key=str.casefold), indent=2)
    )

with open("removed", "w") as removed_file:
    removed_file.write(json.dumps(removedcontent, indent=2))

if remove["repository"].split("/")[0] not in orgs:
    with open(foundcategory, "w") as cat_file:
        cat_file.write(json.dumps(sorted(categorycontent, key=str.casefold), indent=2))
