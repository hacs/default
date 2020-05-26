from scripts.changed.category import get_category
from scripts.helpers.info import get_info


def check():
    info = get_info()
    if not info:
        print("No information provided.")
        exit(1)


if __name__ == "__main__":
    check()
