from scripts.changed.category import get_category
from scripts.helpers.info import get_info


def check():
    if get_category() not in ["plugin", "theme"]:
        print("Only plugin and theme are checked.")
        return

    info = get_info()
    if "<img" in info or "![" in info:
        print("Has image(s)")
        return

    print("There should be images to show the user what they get.")
    exit(1)


if __name__ == "__main__":
    check()
