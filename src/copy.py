"""The words Synchotic puts on screen, in one file.

Edit the strings here rather than hunting them through the screens. Nothing in
this file does anything: the screens import these and fill in the {fields}.
Setup, the home screen's empty states, and anything said on more than one
screen live here; text that appears in exactly one place may still be inline.

    # AI-COPY

marks a string the model wrote that nobody has rewritten yet. Grep for it to
see what is left, and delete the marker when a string is yours. Anything
without one has been through a human.

Placeholders are named, so they can be reordered or dropped: a string that
stops using {path} is fine, one that invents {pathh} raises at render.

Periods: a full sentence ends with one. A title, question, button, label,
status (STATUS_*, LIBRARY_UNSET) or line ending in a path does not. When a
status is joined into a sentence, the code adds the period.

Layout stays out of here: no leading blank lines and no indents after a line
break. The screen that prints a string decides where it sits, so the same
sentence can go in a box, a dialog or the scrollback without being rewritten.
"""


# ===========================================================================
# Before a sync: the check that runs when S is pressed
# ===========================================================================
#
# Each problem is a headline, an optional line of detail, and a fix. Most
# reuse the shared strings above; only what is said nowhere else lives here.
# Nothing is shown at all when there is nothing wrong.

PRE_TITLE_BLOCKED = "Unable to sync"
PRE_FREE = "{size} free"
PRE_ASK = "Sync anyway?"

# {floor} is " at least" while some drives are unmeasured, "" once all are.
PRE_SPACE = "Not enough disk space"
# Fits, but leaves the disk nearly full, or unmeasured drives could tip it over.
PRE_LOW_SPACE = "Low on disk space"  # AI-COPY
PRE_SPACE_DETAIL = "Needs{floor} {needed}, you have {free}."
PRE_FREE_UP = "Free up space, or disable some setlists."

# {charts} comes from count(), e.g. "300 charts".
PRE_PURGE = "This sync will purge {charts}"
PRE_PURGE_DETAIL = "That's {size} from drives and setlists you've disabled."
