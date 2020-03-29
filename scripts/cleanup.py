from github import Github
from datetime import datetime
import json

github = Github("")

removed_authors = []
removed_orgs = []

categories = ["appdaemon", "integration", "netdaemon", "plugin", "python_script", "theme"]
orgs = ["custom-components", "custom-cards", "home-assistant-community-themes"]
category_content = {}


def remove_repo(repo):
    blacklist.append(repo)
    removed.append({"removal_type": "blacklist", "repository": repo})


for category in categories:
    with open(category, "r") as category_file:
        category_content[category] = json.loads(category_file.read())

with open("removed", "r") as removed_file:
    categories["removed"] = json.loads(removed_file.read())
with open("blacklist", "r") as blacklist_file:
    blacklist = json.loads(blacklist_file.read())
with open("grace.json", "r") as grace_file:
        grace = json.loads(grace_file.read())


# Make sure the removed list is up to date
for repo in blacklist:
    if repo not in str(removed):
        removed.append({"removal_type": "stale", "repository": repo, "link": "https://github.com/hacs/default/pull/299"})

for category in categories:
    for repo in category_content[category]:
        if grace.get(repo) is not None:
            if grace[repo]["until"] < datetime.now().timestamp():
                continue
        repository = github.get_repo(repo)
        ago = datetime.today() - repository.pushed_at
        if ago.days > 180 and (repository.open_issues != 0 or len(list(repository.get_pulls())) != 0):
            remove_repo(repo)
            category_content[category].remove(repo)
            if repository.owner.type == "User":
                if repository.owner.login not in removed_authors:
                    removed_authors.append(repository.owner.login)
            else:
                removed_orgs.append(repo)

for org in orgs:
    for repo in github.get_organization(org).get_repos():
        if grace.get(repo) is not None:
            if grace[repo]["until"] < datetime.now().timestamp():
                continue
        repository = github.get_repo(repo)
        ago = datetime.today() - repository.pushed_at
        if ago.days > 180 and (repository.open_issues != 0 or len(list(repository.get_pulls())) != 0):
            remove_repo(repo)
            removed_orgs.append(repo)

with open("removed", "w") as removed_file:
    removed_file.write(json.dumps(removed, indent=2))
with open("blacklist", "w") as blacklist_file:
    blacklist_file.write(json.dumps(blacklist, key=str.casefold, indent=2))

for category in categories:
    with open(category, "w") as category_file:
        category_file.write(json.dumps(category_content[category], key=str.casefold, indent=2))


for repo in removed_orgs:
    repository = github.get_repo(repo)
    contributors = list(repository.get_contributors())
    main_contributor = sorted(contributors, key=lambda x: x.contributions, reverse=True)[0]
    if main_contributor.login not in removed_authors:
        removed_authors.append(main_contributor.login)


with open("output/authors", "w") as authors:
    authors.write(", @".join(removed_authors))