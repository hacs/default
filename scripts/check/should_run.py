from scripts.helpers.event import get_event

def check():
    event = get_event()
    return event


if __name__ == "__main__":
    print(check())