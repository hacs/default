from scripts.changed.category import get_category
from scripts.helpers.manifest import get_manifest

def check():
    if get_category() != "integration":
        print("Only integrations are checked.")
        return

    manifest = get_manifest()
    issues = []

    if manifest.get("domain") is None:
        issues.append("No domain")

    if manifest.get("documentation") is None:
        issues.append("No documentation")

    if manifest.get("issue_tracker") is None:
        issues.append("No issue_tracker")

    if manifest.get("codeowners") is None:
        issues.append("No codeowners")

    if issues:
        for issue in issues:
            print(issue)
        exit(1)


if __name__ == "__main__":
    check()