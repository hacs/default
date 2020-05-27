import json
import os
from glob import glob
from scripts.helpers.manifest import get_manifest


def get_domain():
    manifest = get_manifest()
    return manifest.get("domain")


if __name__ == "__main__":
    print(get_domain())
