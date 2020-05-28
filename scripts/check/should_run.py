import os
import json

def check():
    with open("/home/runner/work/_temp/_github_workflow/event.json", "r") as event_data:
        event = json.loads(event_data.read())

    return event


if __name__ == "__main__":
    print(check())