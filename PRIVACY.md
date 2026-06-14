# Privacy Policy

**Last updated:** April 1, 2026

Synchotic is a desktop application that syncs music game charts from Google Drive. This policy explains what data the app accesses and how it's handled.

## What Synchotic accesses

When you sign in with your Google account, Synchotic requests **read-only** access to Google Drive (`drive.readonly` scope). This is used to:

- List files and folders in shared Google Drive directories (chart setlists)
- Download chart archives to your local machine
- Use your account's API quota for downloads (instead of a shared quota)

Although the `drive.readonly` scope technically permits read access to all Drive files, Synchotic **only** accesses shared drives that you explicitly configure as sync sources. It does not browse, index, or read any of your personal Google Drive files.

## What Synchotic stores

- **OAuth token:** Stored locally on your machine at `.dm-sync/token.json`. This token is never transmitted anywhere other than Google's API servers. You can revoke it at any time by signing out within Synchotic or revoking access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- **Local settings:** Stored in `.dm-sync/` in your configured sync directory. These never leave your machine.

### rclone (authenticated downloads)

For some downloads, Synchotic may use [rclone](https://rclone.org), an established open-source command-line tool. rclone stores its own OAuth token locally at `.dm-sync/rclone/rclone.conf`. This token is transmitted only to Google over HTTPS. It is never sent to any Synchotic-operated server (there are none).

### Bring your own credentials (BYOC)

If you provide your own Google OAuth credentials, either as a `.dm-sync/credentials.json` file or via the `SYNCHOTIC_OAUTH_CLIENT_ID` and `SYNCHOTIC_OAUTH_CLIENT_SECRET` environment variables, they are stored and used locally on your machine only. They are never transmitted to anyone except Google.

## What Synchotic does NOT do

- Collect, transmit, or store any personal information
- Access your email, contacts, calendar, or any non-Drive data
- Send analytics or telemetry
- Communicate with any server other than Google's Drive API

## Data retention and deletion

Synchotic stores your OAuth token and settings locally on your machine. You can delete all stored data at any time by removing the `.dm-sync/` directory, or by signing out within the app (which deletes the token). You can also revoke Synchotic's access to your Google account at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Data sharing

Synchotic does not share any data with third parties. There is no backend server. All operations happen locally on your machine.

## Children's privacy

Synchotic is not directed at children under the age of 13 and does not knowingly collect personal information from children.

## Contact

If you have questions about this policy, open an issue on the [Synchotic GitHub repository](https://github.com/noahbaxter/synchotic) or email noahbaxt@gmail.com.
