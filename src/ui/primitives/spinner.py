"""A spinner for work between two screens that can take a second, so the
wait does not read as a hang. Anything longer belongs in the sync panel,
which can be cancelled."""
import sys
import threading
import time

from .colors import Colors

FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
TICK = 0.08

# Below this, drawing anything at all is a flicker, so quick work stays silent.
QUIET = 0.15


def working(label, work, out=None):
    """Run `work()` with a spinner beside `label` and return its result.

    `label` may be a callable, re-read every frame, for a running count. The
    work runs on a thread only so the spinner can animate; an exception in it
    is re-raised here.
    """
    stream = out or sys.stdout
    if not getattr(stream, "isatty", lambda: False)():
        return work()

    done = {}

    def run():
        try:
            done["value"] = work()
        except BaseException as err:  # re-raised below, on the caller's thread
            done["error"] = err

    thread = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(QUIET)

    frame = 0
    widest = 0
    while thread.is_alive():
        text = label() if callable(label) else label
        widest = max(widest, len(text))
        stream.write(f"\r  {Colors.PRIMARY}{FRAMES[frame % len(FRAMES)]}"
                     f"{Colors.RESET} {text}")
        stream.flush()
        frame += 1
        thread.join(TICK)

    if frame:
        # Wipe the widest line drawn, not the last one: a label that grew and
        # then shrank would leave its own tail on screen.
        stream.write("\r" + " " * (widest + 6) + "\r")
        stream.flush()

    if "error" in done:
        raise done["error"]
    return done.get("value")
