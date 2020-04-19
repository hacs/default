import json

categories = ["blacklist", "appdaemon", "integration", "netdaemon", "plugin", "python_script", "theme"]

for category in categories:
    with open(category, "r") as cat_file:
        content = json.loads(cat_file.read())
        if content != sorted(content, key=str.casefold):
            print(f"{category} is not sorted correctly")
            exit(1)