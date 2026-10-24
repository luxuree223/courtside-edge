# Courtside Edge 0.18.4

Teams by Pace switches between NBA.com published PACE and ESPN Hollinger pace, with source-specific efficiency columns and a retrieval timestamp. NBA.com supports recent-game and playoff filters; Hollinger shows full regular seasons only. Sync Pace appears on both the pace page and selected-game team comparison, where pace is shown beside each team name. Main stats sync refreshes both sources. Dated NBA.com and Hollinger snapshots are included for cold starts and source outages. Each is explicitly marked as saved data; Sync Pace attempts a new source request. NBA.com can time out from cloud hosts. A saved response is marked stale when the source cannot refresh; no locally calculated pace is substituted. Defense tables default to NBA, cache position results and show passing columns first for quarterbacks. Player averages retain decimals and include field goals made beside attempts. New signings can resolve a single primary position from a uniquely matched public player profile; exhibition teams are excluded from roster refresh. Search opens blank.

Player research now puts the game picker first, separates direct profile search from the Consistency finder, and starts stat/recent-game targets blank. NBA position filters offer PG, SG, SF, PF and C only. The mobile defense table uses a narrow rank/logo/abbreviation column to leave room for stats.

Defense vs Position uses the full table with a clear team divider, matchup color guide and spacing beneath the season controls. Rankings uses a consistent SVG arrow on mobile and desktop, places data coverage inside the rankings card, and moves Matchup Opportunities to the bottom.

The owner may provide one server-managed AI connection for every authenticated account using EDGE_SHARED_AI_KEY=1 and OPENAI_API_KEY in the host environment. OPENAI_MODEL selects the owner's model. Account pages show connection status without exposing or changing the shared credential. Sportsbook/provider credentials remain separate. Local Windows owners can opt in with share_with_accounts: true in their private data/ai-config.json; the encrypted key stays outside the source package. Shared AI requests use the owner's API allowance. The public site still requires the owner key to be configured in Render; it is never part of GitHub or this ZIP.

Position-defense values combine all opposing players at one primary position within each game, then average those game totals. They do not divide by player count. The primary-position correction removes the old emergency-role overlap. Player profiles show per-game averages without a totals column, the sport switch is compact, and game selectors use plain Select game/no-games messages.

The signed-in homepage has a pencil beside Your Current Betting Money to edit starting/current amounts and unit size. Balance corrections are separate from wager profit and persist in Firebase and JSON backups. A completed login sync opens the app automatically; Retry appears only for failures.

The public homepage refreshes each sport’s slate and moves to tomorrow only after that sport’s games finish. Signing in checks both current seasons for missing ESPN game logs and verifies roster positions before opening the app. The first sync can take several minutes on a cold free host; source errors are shown with retry and an explicit option to open available records.

Public sports records are shared across hosted accounts. Bets, units, bankroll, API keys, quotes and saved AI research stay private. Server research storage remains temporary on Render Free, while Firebase retains personal trackers. Sign-out prepares a private JSON backup and shows a mobile-friendly save button after signing out.

Defense vs Position now has its own sidebar page with a full comparison table, alphabetical and stat sorting, and selected season/last 5 days/last 14 days/last 28 games per team windows. ESPN roster/depth-chart positions are indexed separately with source URLs and observation times. Current-season G/F/missing labels can be classified using this metadata; original historical rows are retained. Positions describe roster/depth-chart classifications rather than tracked defensive assignments. Each NBA player is counted at one sourced primary position; emergency and secondary roles are excluded. Unresolved positions and missing stat coverage remain visible.

Player research has season/last-5/last-10 averages, position-specific NFL cards with quarterbacks first, five recent-game boxes for both sports, and complete-game-log links. Game and team stats precede the player cards. Team Trends is marked Coming Soon.

Settings → Odds sources accepts The Odds API or SportsGameOdds keys and selects the provider for player-prop refreshes. Provider keys are not included in this package or JSON backups and must be re-entered if the temporary server cache is lost. Refreshing uses the selected provider’s allowance. Exact bookmaker quotes are saved; consensus/fair odds are not treated as actual sportsbook offers. Stats remain from ESPN.

Search the Stats Index supports team averages, minimum averages, named-player averages, top scorers, last-N games, home/road and rest filters. It uses saved data and bounded language patterns rather than pretending to be a general AI. General conversation still uses the optional configured AI connection. Default scope is this season’s regular games; an explicit last-N request can reach the preceding season only as needed unless “this season” is specified.

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
