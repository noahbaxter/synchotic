# Bring Your Own Credentials (BYOC)

Synchotic ships with a shared Google OAuth client. That shared client has a fixed
quota, so when too many people use it at once you can hit a cap and get throttled.
BYOC lets you supply your own Google OAuth client instead. With your own client you
get full-speed downloads on your own quota, with no rclone tier in between. This guide
walks you through creating a Google OAuth client and handing it to Synchotic.

If you just want it to work and do not care about speed, you do not need this. BYOC is
for users hitting the shared-app cap or who want full speed without the rclone tier.

## 1. Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. In the project dropdown at the top, click **New Project**.
3. Give it any name (for example `synchotic`) and click **Create**.
4. Make sure the new project is selected before continuing.

## 2. Enable the Google Drive API

1. In the left menu, go to **APIs and Services -> Library**.
2. Search for **Google Drive API**.
3. Open it and click **Enable**.

## 3. Configure the OAuth consent screen

1. Go to **APIs and Services -> OAuth consent screen**.
2. Choose **User type: External** and click **Create**.
3. Fill in the required fields: app name, user support email, and developer contact
   email. The rest can be left blank.
4. On the **Scopes** step, click **Add or Remove Scopes** and add:

   ```
   https://www.googleapis.com/auth/drive.readonly
   ```

5. On the **Test users** step, add your own Google account. This matters only while the
   app is in Testing status (see the next step), but add yourself anyway so you are
   covered either way.

## 4. IMPORTANT: set Publishing status to "In production"

> **Warning: do not skip this.** This is the single most important step. If you leave the
> app in **Testing** publishing status, Google issues refresh tokens that **expire every
> 7 days**. Synchotic will silently sign you out about once a week, and you will have to
> sign in again every time. Setting the status to **In production** fixes this permanently.

1. Go to **APIs and Services -> OAuth consent screen**.
2. Under **Publishing status**, click **Publish App** to move the app to
   **In production**.

You do **not** need to go through Google's verification process. An app that is
**In production** but **unverified** works fine for BYOC. The only effect of being
unverified is that the first time you sign in, Google shows a one-time
"Google hasn't verified this app" screen. Click **Advanced** and then continue. After
that, your refresh tokens persist and you stay signed in.

To recap the difference:

- **Testing** status: tokens expire every 7 days, you get logged out weekly. Do not use.
- **In production**, unverified: one consent interstitial the first time, then you stay
  signed in. This is what you want.

## 5. Create an OAuth client ID

1. Go to **APIs and Services -> Credentials**.
2. Click **Create Credentials -> OAuth client ID**.
3. For **Application type**, choose **Desktop app**.
4. Give it any name and click **Create**.
5. Google shows your **Client ID** and **Client secret**. Keep this dialog open, or
   click **Download JSON** to save the client file.

## 6. Give the credentials to Synchotic

You have two options. Pick one.

### Option A: credentials file

Save the downloaded client JSON as `credentials.json` inside Synchotic's data directory:

```
.dm-sync/credentials.json
```

This is the `.dm-sync` folder next to Synchotic's other data. The file is the standard
Google OAuth client JSON. Synchotic reads either the `installed` or the `web` key from it,
so the file Google gives you for a Desktop app works as-is.

### Option B: environment variables

Set these two environment variables to the Client ID and Client secret from step 5:

```
SYNCHOTIC_OAUTH_CLIENT_ID
SYNCHOTIC_OAUTH_CLIENT_SECRET
```

If both are set, Synchotic uses them and ignores the credentials file.

## 7. Sign in

Start Synchotic and sign in as normal. You will now be using your own OAuth client, your
own quota, and full-speed downloads. The first sign-in shows the one-time
"Google hasn't verified this app" screen described in step 4; click through it once.

## Troubleshooting

**"It keeps signing me out after about a week."** Your OAuth app is still in **Testing**
publishing status, so Google is expiring your refresh token every 7 days. Go back to
step 4 and set the publishing status to **In production**, then sign in again.
