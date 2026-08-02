import os
from glob import glob


def get_integration_path():
    base = "/tmp/repositories/addition"
    # Per the publishing docs, an integration lives in
    # ROOT/custom_components/<domain>. Scope the search there when the
    # directory exists so repositories that also ship other manifest.json
    # files (add-ons, test fixtures) resolve to the integration; fall back
    # to the whole clone for content_in_root repositories.
    search_root = os.path.join(base, "custom_components")
    if not os.path.isdir(search_root):
        search_root = base

    files = []
    for dir, _, _ in os.walk(search_root):
        files.extend(glob(os.path.join(dir, "*manifest.json")))

    if len(files) != 1:
        print("No manifest")
        exit(1)
    return files.pop().replace("/manifest.json", "")


if __name__ == "__main__":
    print(get_integration_path())
