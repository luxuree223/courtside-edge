# New Firebase project + free research host

This is a prepared setup, not an already-published website. You need your own Google/Firebase and GitHub/Render accounts. The current local installation remains separate and keeps its data.

## Configured project — October 22, 2026

The `courtsideedge-betting` project is on Spark. The `Courtside Edge Web` app is registered, Email/Password sign-in is enabled, and the default Standard Firestore database is in `nam5` with the included per-user rules published. The Render blueprint now contains this project's public web-app configuration. It contains no administrator key or personal tracker data.

Eight live integration checks passed against Firebase: separate signups, required units and empty new trackers, separate synthetic records/JSON exports, blocked cross-user/anonymous access, document validation, stale-save protection, account recovery after losing the local cache, and download-cookie sign-out. Disposable authentication accounts were removed and their generated tracker documents were emptied. No owner database was used. Hosted-site deployment and phone/browser verification remain pending.

For this shared website, continue at section 2 using the existing project. The new-project instructions below are for creating a separate Firebase project; update the three Firebase values in `render.yaml` if you do that.

## 1. Create Firebase sign-in and storage

1. Open https://console.firebase.google.com and create a project. Keep the **Spark** plan; no billing account is required for Spark. Google Analytics is optional for this app.
2. In **Authentication → Sign-in method**, enable **Email/Password**. Do not enable phone/SMS sign-in for this setup.
3. Create the default **Cloud Firestore** database in **production mode**, choose a region, then open its **Rules** tab. Replace the rules with the exact contents of the included `firestore.rules` and publish them. Do not use test-mode rules or allow every signed-in user to read every account.
4. Under **Project settings → Your apps**, register a Web app. Copy `projectId`, `apiKey` and `appId` from its web configuration. These identify the Firebase project; this setup does not need a service-account private key.

## 2. Run the Python app online

1. Upload only the clean source to a GitHub repository using **UPLOAD_TO_GITHUB.md**.
2. Open https://dashboard.render.com and create a **Blueprint** from that repository. Review the included `render.yaml`: Python web service, **Free** plan, no paid disk. Do not select a paid upgrade.
3. Review the configured public Firebase values: `EDGE_FIREBASE_PROJECT_ID`, `EDGE_FIREBASE_API_KEY`, `EDGE_FIREBASE_APP_ID`. They are already supplied for `courtsideedge-betting`; replace them only when deploying against another project.
4. Deploy. The Python runtime version comes from `.python-version`; Render installs `requirements.txt`. One worker is intentional. Keep the backend behind Render's proxy; the supplied forwarded-header setting assumes Render is the only public ingress.
5. Copy the generated HTTPS app URL. Add its hostname to Firebase Authentication's authorized domains. Open that URL on a phone to create an account with an email, password and required unit size.

There is no invitation requirement. Every visitor can create their own account. Firebase rules restrict each tracker to its authenticated user. No one is given access to the local owner's account or API keys.

## 3. Bring your own tracker over

On the current local app, choose **Save JSON Backup**. On the new hosted app, create/sign in to your cloud account, open Settings, choose **Load JSON Backup**, select the file and review the preview. Choose **Replace my tracker** only when the counts and unit amount are right. The file imports bets, starting bankroll, unit size and timezone; passwords, API keys and other accounts are excluded.

Returning to the website and signing in retrieves the cloud-saved tracker. You do not have to load the JSON on every visit. The file is a separate portable backup; browsers cannot silently reopen a file from your Downloads folder, and the file does not sign you in.

## Free-plan limits and remaining checks

Firebase Spark/Firestore and Render Free have quotas. Render Free may sleep and take time to wake; do not rely on it for uninterrupted service or guaranteed scheduled sync. Firestore retains the personal tracker across those research-server restarts, within its quotas. The current cloud payload limit is 750 KB per tracker; account saves stop with an error instead of silently falling back to temporary storage. Export JSON before a tracker reaches that limit.

Game/player history is a rebuildable local cache, not part of the cloud personal tracker. Use Sync Tonight's Results or the season download if a fresh server needs research data. Custom AI rules, screenshot files and locally entered API keys are not cloud-synced in this release. The operator can configure server provider keys separately; sharing their quota requires an explicit `EDGE_SHARED_PROVIDER_KEYS=1` choice. This source package supplies no keys. Hosting being free does not make optional AI or paid odds feeds free.

The integration has both mocked-provider coverage and the live Firebase checks described above. The deployed free host still needs its own browser/phone check before using real data. Create two test accounts, set different unit sizes, save different test records, restart the web service and verify both trackers return separately. Keep a JSON backup during that check.

Official references:

- https://firebase.google.com/docs/projects/billing/firebase-pricing-plans
- https://firebase.google.com/docs/web/setup
- https://firebase.google.com/docs/firestore/use-rest-api
- https://firebase.google.com/docs/firestore/quotas
- https://render.com/docs/free
- https://render.com/docs/deploy-fastapi
