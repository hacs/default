import json
import os
from glob import glob


def get_integration_path():
    files = []
    for dir, _, _ in os.walk("/tmp/repositories/addition"):
        files.extend(glob(os.path.join(dir, "*manifest.json")))

    if len(files) != 1:
        print("No manifest")
        exit(1)
    return files.pop().replace("/manifest.json", "")


if __name__ == "__main__":
    print(get_integration_path())
