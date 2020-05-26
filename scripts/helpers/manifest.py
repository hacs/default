import json
import os
from glob import glob
from scripts.helpers.integration_path import get_integration_path

def get_manifest():
    manifest = f"{get_integration_path()}/manifest.json"
    print(f"Found manifest at {manifest.replace('/tmp/addition','')}")

    with open(manifest, "r") as mf:
        manifest = json.loads(mf.read())

    return manifest or {}