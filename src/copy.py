"""The words Synchotic puts on screen, in one file.

Edit the strings here rather than hunting them through the screens. Nothing in
this file does anything: the screens import these and fill in the {fields}.
Every string a person reads lives here. What stays in the code is what nobody
reads as the app talking: diagnostics ([timing], the debug log), dev-only
output (--help, --first-run), exception text shown as FAILURE: {reason}, the
downloader's log lines that are translated before display, and the nouns
count() pluralises.

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
ROW_SIGN_OUT = "Sign out"
ROW_LIBRARY = "Library"
ROW_OPEN_CHARTS = "Open library"
ROW_LOCATION = "Edit path"
ROW_APP = "App"
ROW_OPEN_DATA = "Open data"
ROW_DRIVES = "Drives"
ROW_ADD_CUSTOM = "Add custom drive"
ROW_RESCAN = "Rescan"

SETTINGS_ACCOUNT = f"{SETTINGS} > {ROW_ACCOUNT}"
SETTINGS_MODE = f"{SETTINGS_ACCOUNT} > {ROW_MODE}"
SETTINGS_SIGN_IN = f"{SETTINGS_ACCOUNT} > {ROW_SIGN_IN}"
SETTINGS_LIBRARY = f"{SETTINGS} > {ROW_LIBRARY}"
SETTINGS_LOCATION = f"{SETTINGS_LIBRARY} > {ROW_LOCATION}"
SETTINGS_OPEN_DATA = f"{SETTINGS} > {ROW_APP} > {ROW_OPEN_DATA}"

FIX_FROM = "Go to {where}."

SCANNING = "Scanning…"

# --- buttons and step names -------------------------------------------------

BTN_BACK = "Back"
BTN_SKIP = "Skip"
BTN_CANCEL = "Cancel"
BTN_CONTINUE = "Continue"
BTN_QUIT = "Quit"
PRESS_ENTER = "Press Enter to continue"

SETUP_TITLE = "FIRST TIME SETUP"
SETUP_REPAIR_TITLE = "SETUP REPAIR"
# Setup needs answers and there is no terminal to ask them in.
SETUP_NEEDS_TERMINAL = "Something is misconfigured. Run Synchotic interactively once to repair."
STEP_LIBRARY = "Chart Library"
STEP_MODE = "Download Mode"
STEP_DRIVES = ROW_DRIVES

# --- deleting ---------------------------------------------------------------

# {what} is DELETION_ANY before a folder is counted and DELETION_ALL after.
DELETION_WARNING = (
    "{warn_open}BE WARNED:{warn_close} {what} in this folder "
    "{warn_open}WILL BE DELETED{warn_close} on sync."
)
DELETION_ANY = "any unmanaged files"
DELETION_ALL = "all {files}"   # {files} is count(n, "unmanaged file")

# --- the library ------------------------------------------------------------

LIBRARY_UNSET = "No library set"
LIBRARY_MISSING = "Library not connected"
FIX_RECONNECT = "Reconnect the drive and sync again."

# --- download mode ----------------------------------------------------------

MODE_NAME_RCLONE = "rclone"
MODE_NAME_BYOC = "BYOC"

# Why a mode cannot download yet. Used as the setup page title, the preflight
# headline, the blocked-sync reason and the settings pane's Mode row.
STATUS_MISCONFIGURED = "{mode} is misconfigured"
STATUS_RCLONE = STATUS_MISCONFIGURED.format(mode=MODE_NAME_RCLONE)
STATUS_BYOC = STATUS_MISCONFIGURED.format(mode=MODE_NAME_BYOC)

STATUS_SIGNED_OUT = "You are signed out"
STATUS_SIGNIN_EXPIRED = "Your sign-in has expired"
FIX_SIGN_IN = f"Sign in again from {SETTINGS_SIGN_IN}, then re-sync."

# How something the user started came out. A failure is printed as
# "FAILURE: {reason}" with the real reason, not advice written for a guess.
# WARNING is for something that went wrong while the rest carried on.
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
WARNING = "WARNING"

# --- files the user handles -------------------------------------------------

BYOC_FILE = "BYOC_SETUP_INSTRUCTIONS.txt"
CREDENTIALS_FILE = "credentials.json"

ANON_LIMIT = ("Many charts may still download, but expect game rips and large "
              "chart packs to fail.")

# --- sync results -----------------------------------------------------------

CANCELLED = "Cancelled"
AND_MORE = "and {n} more"

# --- nothing turned on ------------------------------------------------------

NO_DRIVES = "No drives enabled"
NO_SETLISTS = "No setlists enabled"
TOGGLE_DRIVE = "Press Space to toggle one."
TOGGLE_SETLIST = "Press Tab on a drive to enter it, then Space to toggle."


# ===========================================================================
# Home screen
# ===========================================================================

HOME_NO_DRIVES = f"{NO_DRIVES}. {TOGGLE_DRIVE}"

# A drive's column headers and the rows under its setlists.
COL_CHARTS = "CHARTS"
COL_SIZE = "SIZE"
ENABLE_ALL = "Enable all"
DISABLE_ALL = "Disable all"
REMOVE_FOLDER = "Remove custom drive"

# The footer, lower case. Key names (S, Tab, Space, Esc) stay with the code
# binding them.
FOOTER_SYNCED = "synced"
FOOTER_PANES = "switch panes"
FOOTER_TOGGLE = "enable/disable"
FOOTER_SCAN = SCANNING + " {folder} ({done}/{total}) · {elapsed}"

# Section headings in the drive list, for drives drives.json does not group.
GROUP_CUSTOM = "Custom"
GROUP_OTHER = "Other"


# ===========================================================================
# Custom drives: a Google Drive folder the user adds by link
# ===========================================================================

DRIVE_URL_EXAMPLE = "https://drive.google.com/drive/folders/abc123..."
ADD_HOWTO = ("Paste a Google Drive folder link or ID.\n"
             "The folder must be shared with \"anyone with the link\".\n"
             f"Example: {DRIVE_URL_EXAMPLE}")
ADD_INPUT = "Link or ID: "
NOT_A_FOLDER_LINK = "Not a valid Google Drive folder link"
ADD_ALREADY = "{name} is already in your drives"

REMOVE_BODY = ("'{name}' will be removed from your custom drives.\n"
               "Its charts WILL BE DELETED on next sync.")

SCAN_PROGRESS = SCANNING + " {folders}, {files}"


# ===========================================================================
# Setup step 1: where the charts go
# ===========================================================================

LIBRARY_INTRO = (
    "Synchotic keeps one local folder in sync with the drives and setlists "
    "you choose. {warning} Pick an empty folder or a previous sync folder or "
    "face the consequences..."
)

LIBRARY_QUESTION = "Where should the library live?"
LIBRARY_BROWSE = "Pick a folder"
LIBRARY_TYPE = "Path: "
# The spinner while a picked folder is counted.
LIBRARY_READING = "reading {path}"

FOLDER_CREATE_ASK = "Create {path}?"
FOLDER_NOT_A_FOLDER = FAILURE + ": Not a folder: {path}"

# --- what the folder turned out to be --------------------------------------
#
# Asked after a folder is picked. CONFIRM_Q for an empty folder or an existing
# library. CONFIRM_RISKY_Q when the folder has other stuff in it: the deletion
# warning is shown right above it, and the cursor starts on "No".

CONFIRM_Q = "Use this folder?"
CONFIRM_RISKY_Q = "Are you sure you want to use this folder?"

LIBRARY_USE = "Yes, use this folder"
LIBRARY_PICK_ANOTHER = "No, choose another"

FOLDER_IS_NEW = "This folder is empty."

# {counts} is the folder's contents ("12 chart folders, 89 files, 20
# folders"), with a "+" on the numbers when counting stopped early.

FOLDER_NOT_EMPTY = "{counts}\n\n{warning}"

KNOWN_LIBRARY = "Existing Synchotic library found."

DRIVE_LINE = "  · {name}: {setlists}"

# --- skipped it ------------------------------------------------------------

NO_LIBRARY_BODY = "Synchotic cannot sync until a library folder is set."


# ===========================================================================
# Setup step 2: how the big packs download
# ===========================================================================

MODE_INTRO = (
    "Google prevents anonymous downloads for most popular large chart packs. "
    "To get around this limitation you can choose to authenticate Synchotic "
    "with your Google account in a few different ways."
)

MODE_QUESTION = "How should Synchotic authenticate downloads?"

MODE_RCLONE_LABEL = "Sign in with rclone  (easiest)"
MODE_RCLONE_DESC = (
    "Synchotic can use rclone to greatly simplify the setup process. Sign in "
    "to your Google account to give rclone read-only access and you're done.\n"
    "\n"
    "Note: rclone limits are shared with everyone else using rclone, so it "
    "can be slow.\n"
    "\n"
    "DEPRECATED: Google will retire this option sometime in 2026, so consider "
    "BYOC instead."
)

MODE_BYOC_LABEL = "Bring Your Own Credentials  (best)"
MODE_BYOC_DESC = (
    "You can set up your own Google client ID for zero throttling or shared "
    "limits.\n"
    "\n"
    "Setup takes ~10 minutes and is a bit confusing, but as a reward you get "
    "parallel threading which makes large downloads much faster.\n"
    "\n"
    f"Just follow the step by step tutorial in {BYOC_FILE}."
)

MODE_ANON_LABEL = "No sign-in"
MODE_ANON_DESC = (
    "Do nothing and accept that Google will block certain downloads.\n"
    "\n"
    "This primarily blocks access to game rips and other large chart packs, "
    "but if you mostly sync individual charter drives you maaaaaaay be fine."
)

# --- the mode was picked but never finished ---------------------------------
#
# Each is a STATUS_* title, then BODY, then UNFINISHED_RETRY and BTN_QUIT as
# the answers.

UNFINISHED_NOT_SIGNED_IN = ("Looks like you haven't signed in to Google yet. "
                            "{mode} requires read-only access to a Google account.")
UNFINISHED_RCLONE_BODY = UNFINISHED_NOT_SIGNED_IN.format(mode=MODE_NAME_RCLONE)
UNFINISHED_SIGNIN_BODY = UNFINISHED_NOT_SIGNED_IN.format(mode=MODE_NAME_BYOC)

UNFINISHED_BYOC_BODY = (f"Looks like you haven't added your {CREDENTIALS_FILE} yet. "
                        f"{BYOC_FILE} walks you through creating "
                        "your own Google client ID.")

UNFINISHED_RETRY = "Try again"

# --- rclone -----------------------------------------------------------------

RCLONE_CONSENT = "Please sign in to Google to give rclone read-only access to your Drive."

# --- bring your own credentials ---------------------------------------------

BYOC_STEPS = (f"Follow the steps in {BYOC_FILE}, then put "
              f"{CREDENTIALS_FILE} in the same folder:")

# --- signing in to Google ---------------------------------------------------

SIGNIN_QUESTION = "Sign in to Google?"
SIGNIN_SCOPE = "Synchotic only asks for read-only access to your Drive."
SIGNIN_PRIVACY = "Privacy: https://noahbaxter.dev/synchotic/privacy.html"
SIGNIN_KEYS = "[Y] Sign in    [N] Not now"
SIGNIN_OPENING = ("Opening your browser to sign in.\n"
                  "If nothing opens, use the link printed below.")
SIGNIN_EXPIRED = STATUS_SIGNIN_EXPIRED + ".\n" + FIX_SIGN_IN
NO_BROWSER = "Signing in requires a web browser, and this machine doesn't appear to have one."


# ===========================================================================
# Setup step 3: the last page
# ===========================================================================

# Three paragraphs: READY_LAYOUT, READY_DETECTED (only when setup found an
# existing library, {setlists} being its drives and setlist counts), then
# READY_SYNC.

READY_TITLE = "Here's how this works"
READY_LAYOUT = ("In the left column are chart {bold_open}drives{bold_close} that "
                "contain {bold_open}setlists{bold_close} in the "
                "right column. To enable/disable any drive or "
                "setlist press space. To jump into the setlists list press tab "
                "on a drive.")
READY_DETECTED = "Synchotic has detected the following:\n\n{setlists}"
READY_SYNC = ("To sync press S. This will download, update and delete files to "
              "match exclusively the setlists you've selected.")
READY_GO = "Ready"


# ===========================================================================
# Before a sync: the check that runs when S is pressed
# ===========================================================================
#
# Each problem is a headline, an optional line of detail, and a fix.

PRE_TITLE_BLOCKED = "Unable to sync"

PRE_FREE = "{size} free"
PRE_ASK = "Sync anyway?"

PRE_READONLY = "Library is read-only"
PRE_RCLONE_DEAD = "Google Drive is not responding"
PRE_BYOC_FIX = f"Place your {CREDENTIALS_FILE} in {SETTINGS_OPEN_DATA}."
PRE_ANON = "Some charts may not download"

PRE_UNOWNED = "This folder contains unmanaged charts"
PRE_UNOWNED_DETAIL = ("Same name as a drive you have enabled: {names}{more}. "
                      "Anything inside WILL BE DELETED unless it also exists "
                      "inside a setlist from that drive.")
PRE_UNOWNED_MORE = " " + AND_MORE

# {floor} is PRE_AT_LEAST while some drives are unmeasured, "" once all are.
PRE_SPACE = "Not enough disk space"
PRE_AT_LEAST = " at least"
# Fits, but leaves the disk nearly full, or unmeasured drives could tip it over.
PRE_LOW_SPACE = "Low on disk space"
PRE_SPACE_DETAIL = "Needs{floor} {needed}, you have {free}."
PRE_FREE_UP = "Free up space, or disable some setlists."

# {charts} comes from count(), e.g. "300 charts".
PRE_PURGE = "This sync will purge {charts}"
PRE_PURGE_DETAIL = "That's {size} from drives and setlists you've disabled."


# ===========================================================================
# During a sync: the live panel
# ===========================================================================

# Before the panel opens, while drives are listed.
DISCOVERING = SCANNING + " {done}/{total}"

# The stage word in the panel's title (drawn in capitals), and what the list
# says while empty. SYNC and PURGE also name the run's own rows in the list.
SYNC = "Sync"
PURGE = "Purge"
PHASE_DOWNLOAD = "Download"
PHASE_VERIFY = "Verify"
PHASE_STATS = "Stats"
NOTHING_TO_SHOW = "nothing to show yet"

# The keys under the list, and the divider while the list is filtered or paused.
KEY_SCROLL = "↑↓ scroll"
KEY_ALL_CHARTS = "E all charts"
KEY_ERRORS_ONLY = "E errors only"
SHOWING_ERRORS = "errors only · {n}"
HELD = "paused · END to resume"

NETWORK = "network"
EXTRACTING = "extracting…"

# What the divider says the run is doing.
STAGE_CHECKING = "checking {name}"
# A long check, with how far it has got: "1200/5000" or "3,400 files".
STAGE_CHECKING_COUNT = STAGE_CHECKING + " · {count}"
STAGE_DOWNLOADING = "downloading {name}"
STAGE_RCLONE = "downloading {charts} with rclone"
STAGE_SCANNING_AHEAD = "scanning {name}"

# Rows the run adds to the list that are not charts: a name (a phase word,
# WARNING or a drive), then what happened.
NOTE_SCAN_FAILED = "{setlists} could not be scanned, untouched"
NOTE_PARTIALS = "Partial downloads"
NOTE_DELETED = "{files} deleted"
NOTE_DELETED_SIZE = NOTE_DELETED + " ({size})"

PURGE_CONFIRM = "Delete {files} ({size}) from {name}?"

# --- why a chart failed ------------------------------------------------------
#
# The downloader's messages are written for the log. Each failed row shows one
# of these instead, and the advice line under the counts says what to do.

FAIL_DISK_FULL = "disk full"
FAIL_OFFLINE = "no connection"
FAIL_NEEDS_SIGN_IN = "needs sign-in"
FAIL_RATE_LIMITED = "rate limited"
FAIL_SIGNED_OUT = "signed out"
FAIL_TIMED_OUT = "timed out"
FAIL_CUT_SHORT = "incomplete"
FAIL_GONE = "removed"
FAIL_DRIVE_ERROR = "Google error"
FAIL_FORMAT = "unknown format"
FAIL_UNPACK = "extract failed"
FAIL_UNKNOWN = "failed"

RETRIES_NEXT_SYNC = "These will retry next sync."
NOTHING_TO_FIX = "Nothing to fix."
REPORT_IT = "Please report it at github.com/noahbaxter/synchotic/issues"
FIX_OFFLINE = "Reconnect to your internet and try again."


# ===========================================================================
# After a sync: printed under the panel it leaves behind
# ===========================================================================

ALL_SYNCED = "Everything in sync"
DID_NOT_DOWNLOAD = "{charts} failed to download"
FINISHED_IN = "Finished in {time}"
CONTINUING_IN = "Continuing in 5s (press any key to skip)"


# ===========================================================================
# Startup: what a launch did to an older install
# ===========================================================================

# {what} lists what came across, comma separated.
ADOPTED = "Imported from a previous install: {what}"
ADOPT_SKIPPED = ("Found settings from another install in {path}\n"
                 "This install already has its own, so they were not imported.")
MARKERS_LEFT = "{markers} could not be moved, retrying next launch"
SANITIZED = "Renamed {paths} to remove illegal characters:"

MIGRATE_CUSTOM = "Moving custom drive: {old} → {new}"
MIGRATE_EXISTS = FAILURE + ": '{target}' already exists"
