# Courtside Edge

NBA/NFL game research and a personal betting tracker, with mobile layouts.

The homepage opens without signing in and shows the public slate. Use the obvious Sign in / Create account buttons when ready. Create an account with a username or email, a password and a unit size. Usernames are case insensitive, use 3–30 letters, numbers or underscores, and have no recovery email. Existing email accounts continue to work. A unit is your standard bet amount; signup explains it with an example. Accounts have separate bets and money settings. Save JSON Backup downloads a private device copy; Load JSON Backup previews and restores it after sign-in. A JSON file does not contain a password or automatically sign you in.

## Game and player research

The player finder has a Back to full slate arrow. Selecting a game displays ESPN players and either this season’s regular-season averages or that game’s recorded stats. Click a player for five recent-game boxes and any saved props for that exact game, including line, odds, book and observation time. Fewer than five recorded games leave labeled empty boxes; earlier seasons are not substituted. NBA game boxes show points, rebounds and assists. NFL boxes show passing yards/TDs for QBs, receiving yards/targets/TDs for WRs and TEs, and rushing yards/TDs for RBs. Rosters do not certify participation. Missing stats and unavailable sportsbook prices remain labeled rather than estimated. Live games refresh while their research page is open.

## Use it while your computer is off

The optional cloud setup uses **Firebase Authentication + Firestore** for personal account data and a **Render Free Python web service** for the research backend. Your computer does not need to stay on. See [FIREBASE_SETUP.md](FIREBASE_SETUP.md) for the new-project steps and [UPLOAD_TO_GITHUB.md](UPLOAD_TO_GITHUB.md) for uploading this code.

The included `render.yaml` requests a free instance and supplies the configured `courtsideedge-betting` Firebase project's public web-app identifiers. Firebase remains on Spark. Free plans have quotas and the web service can sleep between visits; this is not a guaranteed-uptime service. Unpacking this package does not deploy the website. See FIREBASE_SETUP.md for the completed Firebase checks and remaining deployment steps.

GitHub stores the code. GitHub Pages cannot run this Python/SQLite backend. Use the hosted app's URL after deployment.

## Local use

Install Python 3.11 or newer, extract this package and run `start_windows.bat` on Windows or `start_mac_linux.sh` on macOS/Linux. First launch installs requirements. The local app opens at `http://127.0.0.1:8765`. Firebase is optional and disabled locally unless explicitly configured.

## Data and scope

This source package contains no saved bets, personal database, passwords, private provider credentials, chats or original personal bet examples. The Firebase web configuration is public and relies on the published per-user security rules. Keep personal JSON/ZIP backups outside this repository.

Cloud mode persists bets, starting bankroll, unit size and timezone in the signed-in user's Firestore document. It restores those records when the research server's cache is lost. Saves use revision checks to prevent overwriting another device's changes. Credentials are managed by Firebase; per-user security rules are included. The cloud tracker currently supports a payload up to 750 KB; JSON backups support up to 8 MB.

Public game/player history is a rebuildable server cache and may need syncing after a cold start. Locally saved provider keys, custom AI instructions and screenshot files are not in the Firestore tracker; a free host restart can lose those cache-local files. Optional AI and sportsbook providers have their own access and pricing. Research does not place bets or claim validated win probabilities or expected value.
