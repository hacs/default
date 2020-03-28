from github import Github
from datetime import datetime
import json

github = Github()

removed_authors = []

with open("removed", "r") as removed_file:
    removed = json.loads(removed_file.read())
with open("blacklist", "r") as blacklist_file:
    blacklist = json.loads(blacklist_file.read())
with open("appdaemon", "r") as appdaemon_file:
    appdaemon = json.loads(appdaemon_file.read())
with open("integration", "r") as integration_file:
    integration = json.loads(integration_file.read())
with open("netdaemon", "r") as netdaemon_file:
    netdaemon = json.loads(netdaemon_file.read())
with open("plugin", "r") as plugin_file:
    plugin = json.loads(plugin_file.read())
with open("python_script", "r") as python_script_file:
    python_script = json.loads(python_script_file.read())
with open("theme", "r") as theme_file:
    theme = json.loads(theme_file.read())

def remove_repo(repo):
    blacklist.append(repo)
    removed.append({"removal_type": "blacklist", "repository": repo})



# Make sure the removed list is up to date
for repo in blacklist:
    if repo not in str(removed):
        removed.append({"removal_type": "stale/abandoned", "repository": repo})


for repo in netdaemon:
    repository = github.get_repo(repo)
    if repository.owner.type == "User":
        ago = datetime.today() - repository.updated_at
        if ago > (365 / 2) and repository.open_issues != 0 and len(list(repo.get_pulls())) != 0:
            removed_authors.append(repo.owner.login)
            remove_repo(repo)
            netdaemon.remove(repo)
























with open("removed", "w") as removed_file:
    removed_file.write(json.dumps(removed, sort_keys=True, indent=4))
with open("blacklist", "w") as blacklist_file:
    blacklist_file.write(json.dumps(blacklist, sort_keys=True, indent=4))
with open("appdaemon", "w") as appdaemon_file:
    appdaemon_file.write(json.dumps(appdaemon, sort_keys=True, indent=4))
with open("integration", "w") as integration_file:
    integration_file.write(json.dumps(integration, sort_keys=True, indent=4))
with open("netdaemon", "w") as netdaemon_file:
    netdaemon_file.write(json.dumps(netdaemon, sort_keys=True, indent=4))
with open("plugin", "w") as plugin_file:
    plugin_file.write(json.dumps(plugin, sort_keys=True, indent=4))
with open("python_script", "w") as python_script_file:
    python_script_file.write(json.dumps(python_script, sort_keys=True, indent=4))
with open("theme", "w") as theme_file:
    theme_file.write(json.dumps(theme, sort_keys=True, indent=4))

with open("output/authors", "w") as authors:
    authors.write(", @".join(removed_authors))