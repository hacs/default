import os
import json


def get_event():
    with open(os.getenv("GITHUB_EVENT_PATH"), "r") as event_data:
        event = json.loads(event_data.read())

    return event
