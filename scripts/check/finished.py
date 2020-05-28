from scripts.helpers.event import get_event

def check():
    event = get_event()
    labels = event.get("pull_request", {}).get("labels", [])

    for label in labels:
        if label["name"] == "Not finished":
            exit("::error::Pull request is not ready for CI runs")


if __name__ == "__main__":
    check()