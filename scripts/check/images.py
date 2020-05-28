from scripts.changed.category import get_category
from scripts.helpers.info import get_info


def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-images")
    if get_category() not in ["plugin", "theme"]:
        print("Only plugin and theme are checked.")
        return

    info = get_info()
    if "<img" in info or "![" in info:
        print("Has image(s)")
        return

    exit("::error::There should be images to show the user what they get.")


if __name__ == "__main__":
    check()
