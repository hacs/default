from scripts.changed.category import get_category
from scripts.helpers.info import get_info


def check():
    print("Information: https://hacs.xyz/docs/publish/include#check-info")
    info = get_info()
    if not info:
        print("No information provided.")
        exit(1)


if __name__ == "__main__":
    check()
