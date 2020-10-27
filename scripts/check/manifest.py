from scripts.changed.category import get_category
from scripts.helpers.manifest import get_manifest
from scripts.helpers.integration_path import get_integration_path


def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-manifest")
    if get_category() != "integration":
        print("Only integrations are checked.")
        return

    fail = "::error::Missing required value for key '{key}' in {path}"
    integration = get_integration_path()
    path = f"{integration.replace('/tmp/repositories/addition/', '')}/manifest.json"

    manifest = get_manifest()
    issues = []

    if manifest.get("domain") is None or manifest.get("domain") == "":
        issues.append(fail.format(key="domain", path=path))

    if manifest.get("documentation") is None or manifest.get("documentation") == "":
        issues.append(fail.format(key="documentation", path=path))

    if manifest.get("issue_tracker") is None or manifest.get("issue_tracker") == "":
        issues.append(fail.format(key="issue_tracker", path=path))

    if manifest.get("codeowners") is None:
        issues.append(fail.format(key="codeowners", path=path))

    if issues:
        for issue in issues:
            print(issue)
        exit(1)


if __name__ == "__main__":
    check()
