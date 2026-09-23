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
# Shared: said on more than one screen, so said one way
# ===========================================================================

# --- settings rows, and the pointers built from them ------------------------
#
# The home screen's settings pane labels its rows with these, and every "go to
# X" pointer is built from them, so renaming a row cannot leave a pointer aimed
# at a row that is not there.

SETTINGS = "Settings"
ROW_ACCOUNT = "Account"
ROW_MODE = "Mode"
ROW_SIGN_IN = "Sign in to Google"
ROW_LIBRARY = "Library"
ROW_LOCATION = "Edit path"
ROW_APP = "App"
ROW_OPEN_DATA = "Open data"

SETTINGS_ACCOUNT = f"{SETTINGS} > {ROW_ACCOUNT}"
SETTINGS_MODE = f"{SETTINGS_ACCOUNT} > {ROW_MODE}"
SETTINGS_SIGN_IN = f"{SETTINGS_ACCOUNT} > {ROW_SIGN_IN}"
SETTINGS_LIBRARY = f"{SETTINGS} > {ROW_LIBRARY}"
SETTINGS_LOCATION = f"{SETTINGS_LIBRARY} > {ROW_LOCATION}"
SETTINGS_OPEN_DATA = f"{SETTINGS} > {ROW_APP} > {ROW_OPEN_DATA}"

FIX_FROM = "Go to {where}."

# --- the library ------------------------------------------------------------

LIBRARY_UNSET = "No library set"
LIBRARY_MISSING = "Library not connected"
FIX_RECONNECT = "Reconnect the drive and sync again."

# --- download mode ----------------------------------------------------------

MODE_NAME_RCLONE = "rclone"
MODE_NAME_BYOC = "BYOC"

# Why a mode cannot download yet. Used as the setup page title, the preflight
# headline, the blocked-sync reason and the home screen hint.
STATUS_MISCONFIGURED = "{mode} is misconfigured"
STATUS_RCLONE = STATUS_MISCONFIGURED.format(mode=MODE_NAME_RCLONE)
STATUS_BYOC = STATUS_MISCONFIGURED.format(mode=MODE_NAME_BYOC)

STATUS_SIGNED_OUT = "You are signed out"
STATUS_SIGNIN_EXPIRED = "Your sign-in has expired"
FIX_SIGN_IN = f"Sign in again from {SETTINGS_SIGN_IN}, then re-sync."

CREDENTIALS_FILE = "credentials.json"

ANON_LIMIT = ("Many charts may still download, but expect game rips and large "
              "chart packs to fail.")

# --- nothing turned on ------------------------------------------------------

NO_DRIVES = "No drives enabled"
NO_SETLISTS = "No setlists enabled"
TOGGLE_DRIVE = "Press Space to toggle one."
TOGGLE_SETLIST = "Press Tab on a drive to enter it, then Space to toggle."


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

PRE_READONLY = "Library is read-only"
PRE_RCLONE_DEAD = "Google drive is not responding"
PRE_BYOC_FIX = f"Place your {CREDENTIALS_FILE} in {SETTINGS_OPEN_DATA}."
PRE_ANON = "Some charts may not download"

PRE_UNOWNED = "This folder contains unmanaged charts"
PRE_UNOWNED_DETAIL = ("Same name as a drive you have enabled: {names}{more}. "
                      "Anything inside WILL BE DELETED unless it also exists "
                      "inside a setlist from that drive.")
PRE_UNOWNED_MORE = " and {n} more"

# {floor} is " at least" while some drives are unmeasured, "" once all are.
PRE_SPACE = "Not enough disk space"
# Fits, but leaves the disk nearly full, or unmeasured drives could tip it over.
PRE_LOW_SPACE = "Low on disk space"  # AI-COPY
PRE_SPACE_DETAIL = "Needs{floor} {needed}, you have {free}."
PRE_FREE_UP = "Free up space, or disable some setlists."

# {charts} comes from count(), e.g. "300 charts".
PRE_PURGE = "This sync will purge {charts}"
PRE_PURGE_DETAIL = "That's {size} from drives and setlists you've disabled."
