# Private accounts and mobile access

For the optional Firebase/Render free-tier setup, follow **FIREBASE_SETUP.md**. It uses Firebase email/password sign-in instead of local usernames and saves personal trackers to Firestore across research-server restarts. The new project and host are not yet created or connected. The instructions below describe the ordinary local/persistent-server mode.

Your current personal ZIP, database, backups and `data/` folder are private. Do not send them to friends.

Use the **CLEAN_SHARE** package for another installation or a new hosted instance. It contains code, team artwork and this guide. It contains no database, saved bets, settings, keys, chat, snapshots, account credentials or personal project notes. The original personal bet examples are removed from this package. A new installation starts with zero bets and a $0 balance; every person chooses a unit size when creating their account.

## Separate accounts

On your current app, choose **Set up / Sign in** to protect your existing database. Your current unit amount is prefilled in this owner setup form; keep it or choose a different amount. Once the owner is set up and the site is hosted, friends simply open the website, enter a username, password and unit size, and tap **Create account & get started**. No invitation or approval is required. They receive an empty tracker and separate settings and API-key storage. The unit explanation says: a unit is a standard bet amount; if one unit is $5, a two-unit bet is $10. It can be changed later in Settings.

Saved entries live in that person's server account. They can close the phone browser and sign in later or on another device to access the same saved tracker. Returning users use **Already have an account? Sign in** and do not need to choose their unit size again. Initial public game/player research is copied into each account; personal bets, money settings, custom AI instructions and keys are never copied. Each account syncs its own records.

Sign-out first saves and verifies a personal data ZIP on the server device, then downloads a copy to the browser device. If saving fails, the account stays signed in. Browsers may require a download confirmation or use a Files/Downloads location on a phone. If a browser declines the download, the server copy still exists in that account's `backups/` folder. Other accounts and active sessions are excluded from the backup. Backups contain private data and must not be used as sharing packages.

**Save JSON Backup** also downloads a small personal file to the phone or computer. It contains bets, starting bankroll, unit size and timezone. **Load JSON Backup** previews and restores these after sign-in; it does not contain passwords or keys. In Firebase cloud mode, sign-out uses this JSON download rather than the local-server ZIP. Returning users normally retrieve cloud-saved information by signing in and only need the file for a separate restore or migration.

## A phone needs a reachable app URL

The desktop ZIP does not run on a phone. A mobile browser can use the responsive website once a server hosts it at an HTTPS address. `127.0.0.1:8765` refers to the device opening the address; it is not a link your friend can use remotely.

No deployment, public access, paid hosting or account sharing has been enabled by this update. Choose a hosting service/account before publishing. Build the clean package's Dockerfile or install its Python requirements. Use a persistent private disk/volume for `/data` so profiles survive restarts.

Required hosted environment:

- `EDGE_DB_PATH=/data/edge.sqlite3`
- `EDGE_REQUIRE_AUTH=1`
- `EDGE_SETUP_TOKEN`: a long random secret chosen by the operator, entered only during initial owner setup. There is no default password or setup code.
- HTTPS through a properly configured reverse proxy. Keep the backend private to that proxy; configure forwarded headers only for the actual trusted proxy address. Initial owner setup should be completed before handing out the URL.

After owner setup, share the hosted website URL. Anyone visiting it can create their own account. Do not give them your password or personal backup. Everyone's tracker and account files are separate; an operator with server filesystem access can still read unencrypted database files. This is account isolation, not encryption of the betting ledger.

Provider connections: by default, accounts use their own saved keys. Server environment keys are available only to the owner. An operator may explicitly set `EDGE_SHARED_PROVIDER_KEYS=1` to let other accounts use those server keys; this shares the provider quota/cost, not the secret key or personal data. Do not enable it unless you want to pay for that shared usage. Windows installations support protected per-account OpenAI keys. On other operating systems, configure the provider through server environment settings. Optional Covers browser capture requires Playwright's Chromium browser and its system dependencies on the host.

Keep the private data disk backed up and protect the hosting account. App sign-in does not replace host administration and HTTPS. Sportsbook prices and research remain informational; the app never places bets.
