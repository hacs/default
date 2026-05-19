import json

categories = [
    "blacklist",
    "appdaemon",
    "integration",
    "netdaemon",
    "plugin",
    "python_script",
    "template",
    "theme",
]

for category in categories:
    with open(category, "r") as cat_file:
        content = json.loads(cat_file.read())

    with open(category, "w") as cat_file:
        cat_file.write(json.dumps(sorted(content, key=str.casefold), indent=2))
