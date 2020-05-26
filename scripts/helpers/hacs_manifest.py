import json
import os
from glob import glob

def get_hacs_manifest():
    files = []
    for dir,_,_ in os.walk("/tmp/addition"):
        files.extend(glob(os.path.join(dir, "*hacs.json")))

    if len(files) != 1:
        print("No HACS manifest")
        exit(1)

    with open(files.pop(), "r") as mf:
        hacs_manifest = json.loads(mf.read())

    return hacs_manifest or {}