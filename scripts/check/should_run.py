import os
import json

def check():
    with open(os.getenv("GITHUB_EVENT_PATH"), "r") as event_data:
        event = json.loads(event_data.read())

    print(event)


if __name__ == "__main__":
    print(check())