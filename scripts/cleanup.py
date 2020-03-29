from github import Github
from datetime import datetime
import json
import os

github = Github(os.getenv("GITHUB_TOKEN"))

removed_authors = []
removed_orgs = []

categories = ["appdaemon", "integration", "netdaemon", "plugin", "python_script", "theme"]
orgs = ["custom-components", "custom-cards", "home-assistant-community-themes"]
category_content = {}

cutoff = datetime(year=2019, month=10, day=1) # > 180 days

def remove_repo(repo):
    if repo not in str(blacklist):
        blacklist.append(repo)
    if repo not in str(removed):
        removed.append({"removal_type": "stale", "repository": repo, "link": "https://github.com/hacs/default/pull/299"})


for category in categories:
    with open(category, "r") as category_file:
        category_content[category] = json.loads(category_file.read())

with open("removed", "r") as removed_file:
    removed = json.loads(removed_file.read())
with open("blacklist", "r") as blacklist_file:
    blacklist = json.loads(blacklist_file.read())
with open("grace.json", "r") as grace_file:
    grace = json.loads(grace_file.read())


# Make sure the removed list is up to date
for repo in blacklist:
    if repo not in str(removed):
        removed.append({"removal_type": "blacklist", "repository": repo})

for category in categories:
    for repo in category_content[category]:
        print(repo)
        if grace.get(repo) is not None:
            if grace[repo]["until"] > datetime.now().timestamp():
                continue
        repository = github.get_repo(repo)
        if repository.pushed_at < cutoff and (repository.open_issues != 0 or len(list(repository.get_pulls())) != 0):
            remove_repo(repo)
            category_content[category].remove(repo)
            if repository.owner.type == "User":
                if repository.owner.login not in removed_authors:
                    removed_authors.append(repository.owner.login)
            else:
                removed_orgs.append(repo)

for org in orgs:
    for repo in github.get_organization(org).get_repos():
        print(repo.full_name)
        if grace.get(repo.full_name) is not None:
            if grace[repo.full_name]["until"] > datetime.now().timestamp():
                continue
        repository = repo
        if repository.pushed_at < cutoff and (repository.open_issues != 0 or len(list(repository.get_pulls())) != 0):
            remove_repo(repo.full_name)
            removed_orgs.append(repo.full_name)

with open("removed", "w") as removed_file:
    removed_file.write(json.dumps(removed, indent=4))
with open("blacklist", "w") as blacklist_file:
    blacklist_file.write(json.dumps(sorted(blacklist, key=str.casefold), indent=2))

for category in categories:
    with open(category, "w") as category_file:
        category_file.write(json.dumps(sorted(category_content[category], key=str.casefold), indent=2))


for repo in removed_orgs:
    if repo not in str(removed) or repo not in str(blacklist):
        repository = github.get_repo(repo)
        contributors = list(repository.get_contributors())
        main_contributor = sorted(contributors, key=lambda x: x.contributions, reverse=True)[0]
        with open("output/orgs", "a") as orgs:
            orgs.write(f"{repo} - @{main_contributor.login}")
        if main_contributor.login not in removed_authors:
            removed_authors.append(main_contributor.login)


with open("output/authors", "w") as authors:
    authors.write(", @".join(removed_authors))