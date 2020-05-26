import json
import os
from glob import glob

def get_manifest():
    files = []
    for dir,_,_ in os.walk("/tmp/addition"):
        files.extend(glob(os.path.join(dir, "*manifest.json")))

    if len(files) != 1:
        print("No manifest")
        exit(1)

    with open(files.pop(), "r") as mf:
        manifest = json.loads(mf.read())

    return manifest or {}