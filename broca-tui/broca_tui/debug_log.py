"""Simple debug logger that writes to /tmp/broca-tui-debug.log"""

LOG_FILE = "/tmp/broca-tui-debug.log"

def log(msg: str):
    """Write debug message to log file with timestamp."""
    import datetime
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def clear():
    """Clear the log file."""
    with open(LOG_FILE, "w") as f:
        f.write("")
