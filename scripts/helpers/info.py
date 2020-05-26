import os
from scripts.helpers.hacs_manifest import get_hacs_manifest

ALTERNATIVES = {
    "info": ["info", "INFO", "info.md", "INFO.md", "info.MD", "INFO.MD"],
    "readme": ["readme", "README", "readme.md", "README.md", "readme.MD", "README.MD"],
}


def get_info():
    manifest = get_hacs_manifest()
    info = "readme" if manifest.get("render_readme", False) else "info"

    content = ""

    for alternative in ALTERNATIVES[info]:
        if os.path.exists(f"/tmp/addition/{alternative}"):
            with open(f"/tmp/addition/{alternative}", "r") as alt:
                content = alt.read()
    return content
