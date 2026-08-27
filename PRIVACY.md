# Synchotic Privacy Policy

*Last updated April 21, 2026.*

**Canonical version:** <https://noahbaxter.dev/synchotic/privacy.html>

## Use of Google API User Data

Synchotic is a desktop application to sync music game charts from Google Drive. Its sole purpose is to access and manipulate user content in Google Drive from a local machine of the end user. For accessing the user content via the Google Drive API, Synchotic uses authentication mechanisms, such as OAuth, depending on the particular Google Drive API offerings. Use of these authentication mechanisms and user data is governed by the privacy policies mentioned in the Resources & Further Information section and followed by the privacy policy of Synchotic.

- Synchotic provides the end user with access to their files available in Google Drive associated by the authentication credentials via the publicly exposed API of Google Drive.
- Synchotic allows storing the authentication credentials on the user machine in the local configuration file.
- Synchotic does not share any user data with third parties.

Synchotic requests the `drive.readonly` OAuth scope. Although this scope technically permits read access to all Drive files, Synchotic only accesses the folders you configure as sync sources. These include the community drives you enable within the app, as well as any custom Google Drive folders you add yourself. Synchotic does not browse, index, or read any other files in your Google Drive.

## User Data Collection and Storage

This section outlines how Synchotic accesses, uses, stores, and shares user data obtained from Google Drive APIs. Our use of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

Synchotic is a client-side application that users run on their own computers to manage their files on Google Drive. The Synchotic project does not operate any servers that store or process your personal data. All data access and processing occurs directly on the user's machine and between the user's machine and the Google API servers.

### rclone (authenticated downloads)

For some downloads, Synchotic may use [rclone](https://rclone.org), an established open-source command-line tool. rclone stores its own OAuth token locally at `.dm-sync/rclone/rclone.conf`. This token is transmitted only to Google over HTTPS. It is never sent to any Synchotic-operated server (there are none).

### Bring your own credentials (BYOC)

If you provide your own Google OAuth credentials, either as a `.dm-sync/credentials.json` file or via the `SYNCHOTIC_OAUTH_CLIENT_ID` and `SYNCHOTIC_OAUTH_CLIENT_SECRET` environment variables, they are stored and used locally on your machine only. They are never transmitted to anyone except Google.

## Data Accessed

When you authorize Synchotic to access your files on Google Drive, it may access the following types of data, depending on the permissions you grant:

- **Files:** Synchotic accesses the metadata (filenames, sizes, modification times, etc.) and content of your files and folders on Google Drive. This is necessary for Synchotic to perform file management tasks like listing and downloading charts.
- **Authentication Tokens:** Synchotic requests OAuth 2.0 access tokens from Google. These tokens are used to authenticate your requests to the Google APIs and prove that you have granted Synchotic permission to access your data.
- **Basic Profile Information:** As part of the authentication process, Synchotic may receive your email address to identify the connected account within the Synchotic configuration.

## Data Usage

Synchotic uses the user data it accesses solely to provide its core functionality, which is initiated and controlled entirely by you, the user. Specifically:

- The data is used to perform file transfer and management operations (such as listing and downloading charts) between your local machine and your Google Drive account as per your direct commands.
- Authentication tokens are used exclusively to make authorized API calls to Google's services on your behalf.
- Your email address is used locally to help you identify which Google account is configured.

Synchotic does not use your data for any other purpose, such as advertising, marketing, or analysis by the Synchotic project developer.

## Data Sharing

Synchotic does not share your user data with any third parties.

All data transfers initiated by the user occur directly between the machine where Synchotic is running and Google's servers. The Synchotic project and its developer **never** have access to your authentication tokens or your file data.

## Data Storage & Protection

- **Configuration Data:** Synchotic stores its configuration, including the OAuth 2.0 tokens required to access your Google account, in a configuration file (`.dm-sync/token.json`) located on your local machine.
- **Security:** The OAuth token is stored only on your local machine, transmitted only to Google over HTTPS, and never sent to any Synchotic-operated server (there are no such servers). You are responsible for securing this configuration file on your own computer.
- **File Data:** Your file data is only held in your computer's memory (RAM) temporarily during sync operations. Synchotic does not permanently store your file content on your local disk unless you explicitly command it to do so (e.g., by running a sync to download chart archives to a local directory).

## Data Retention & Deletion

Synchotic gives you full control over your data.

- **Data Retention:** Synchotic retains the configuration data, including authentication tokens, on your local machine for as long as you keep the configuration file. This allows you to use Synchotic without having to re-authenticate for every session.
- **Data Deletion:** You can delete your data and revoke Synchotic's access at any time through one of the following methods:
    1. **In-app sign out:** Sign out within Synchotic to delete the token file from your local machine.
    2. **Local Deletion:** You can delete the `.dm-sync/token.json` file, or delete the entire `.dm-sync/` directory. This will permanently remove the authentication tokens from your machine.
    3. **Revoking Access via Google:** You can revoke Synchotic's access to your Google account directly from your Google account security settings page. This will invalidate the authentication tokens, and Synchotic will no longer be able to access your data. You can manage your permissions on the [Google permissions page](https://myaccount.google.com/permissions).

## Children's Privacy

Synchotic is not directed at children under the age of 13 and does not knowingly collect personal information from children.

## Contact

If you have questions about this policy, open an issue on the [Synchotic GitHub repository](https://github.com/noahbaxter/synchotic) or email <noahbaxt@gmail.com>.

## Resources & Further Information

- [Google Privacy Policy](https://policies.google.com/privacy)
- [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
- [Manage Google account permissions](https://myaccount.google.com/permissions)
