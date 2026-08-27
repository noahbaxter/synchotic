"""Line input with a Browse hotkey.

chotic_ui's input_with_esc is the shared primitive and stays as it is. Only the
library screen needs a way out to a native dialog, so it lives here rather than
putting a Synchotic-shaped hole in the toolkit.
"""

from chotic_ui.primitives.keyboard_input import CancelInput, getch


class Browse(Exception):
    """The user asked for the folder dialog instead of typing a path."""


def input_with_browse(prompt: str = "", browse_key: str = "b") -> str:
    """Read a line. ESC raises CancelInput, browse_key raises Browse.

    Browse only fires while nothing is typed, so the letter stays usable
    everywhere else in a path. That does mean a relative path starting with
    that letter cannot be typed, which is why the prompt says so and why
    cancelling the dialog puts you back here with the line still empty.
    """
    if prompt:
        print(prompt, end="", flush=True)

    result = []
    while True:
        ch = getch()

        if not ch:  # ignored key, e.g. an arrow
            continue
        elif ch == "\x1b":  # ESC
            print()
            raise CancelInput()
        elif ch in ("\r", "\n"):  # Enter
            print()
            return "".join(result)
        elif ch in ("\x7f", "\x08"):  # Backspace
            if result:
                result.pop()
                print("\b \b", end="", flush=True)
        elif not result and ch.lower() == browse_key:
            print()
            raise Browse()
        elif ch >= " ":  # printable
            result.append(ch)
            print(ch, end="", flush=True)
