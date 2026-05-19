import json

# Information https://hacs.xyz/docs/publish/remove
REMOVED_PUBLISHERS = [
    {
        "publisher": "reharmsen",
        "link": "https://github.com/hacs/integration/issues/2192",
    },
    {
        "publisher": "fred-oranje",
        "link": "https://github.com/hacs/integration/issues/2748",
    },
    {
        "publisher": "kraineff",
        "link": "https://github.com/hacs/integration/issues/2986",
    },
]

CATEGORIES = [
    "appdaemon",
    "integration",
    "netdaemon",
    "plugin",
    "python_script",
    "template",
    "theme",
]

TO_REMOVE = {category: [] for category in CATEGORIES}
for entry in REMOVED_PUBLISHERS:
    for category in CATEGORIES:
        with open(category, "r") as cat_file:
            content = json.loads(cat_file.read())
            for key in content.copy():
                if entry["publisher"] in key.lower():
                    print(f"Found {key} in {category}")
                    TO_REMOVE[category].append(
                        {"repository": key, "link": entry["link"]}
                    )

with open("blacklist", "r") as blacklist_file:
    blacklistcontent = json.loads(blacklist_file.read())

with open("removed", "r") as removed_file:
    removedcontent = json.loads(removed_file.read())

for category in TO_REMOVE:
    if len(TO_REMOVE[category]) != 0:
        with open(category, "r") as cat_file:
            categorycontent = json.loads(cat_file.read())

        for entry in TO_REMOVE[category]:
            blacklistcontent.append(entry["repository"])
            removedcontent.append(
                {**entry, "reason": "Author removed", "removal_type": "removal"}
            )
            categorycontent.remove(entry["repository"])

        with open(category, "w") as cat_file:
            cat_file.write(
                json.dumps(sorted(categorycontent, key=str.casefold), indent=2)
            )


with open("blacklist", "w") as blacklist_file:
    blacklist_file.write(
        json.dumps(sorted(blacklistcontent, key=str.casefold), indent=2)
    )

with open("removed", "w") as removed_file:
    removed_file.write(json.dumps(removedcontent, indent=2))
