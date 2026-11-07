# Initial Hestia port verification

Verified in a disposable VMware Hestia 1.10.6 installation with PHP 8.3 and MariaDB. No production sites were used. These results cover the native Apache + PHP-FPM topology; other Hestia versions/topologies still require their own compatibility check.

## Backend and panel authorization

- Isolated Linux/root regression tests cover account ownership, role checks, suspension/target changes, ZIP integrity and identity, unsafe paths/links, account UID isolation, uploads, retention, downloads and pending premium entries.
- Native Hestia admin login renders the addon; wrong CSRF tokens and ordinary hosting-user GET/POST requests are rejected.
- Repeated installation works. Uninstall/reinstall preserves private packages, backups and history. Uninstall refuses an active job.

## Actual update workflow

- A dedicated hosting account contains a primary WordPress installation, a second installation in a subdirectory and a separate plain HTML domain. Discovery lists the two WordPress installations with separate IDs and excludes HTML.
- Browser buttons update both installations from WordPress 6.7.2 to the available upstream version, including database, Akismet and themes, with plugin/theme/database backups first.
- A deliberately expired-license update provider creates exactly one empty **Awaiting premium ZIP** record. The free update and the other installation complete. HTTP/network errors are tested separately and do not become premium entries.
- Uploading the matching package fills the pending record. Its premium-only update button installs version 2.0 over the existing 1.0 plugin without activating it.
- A real vendor WPBakery 8.7.2 ZIP was accepted independently of its download filename and installed under the hosting account UID without activation. That proprietary ZIP and all credentials remain outside Git and the distribution.
- Names in both site lists link to their correct primary/subdirectory URL with `target="_blank"` and `rel="noopener noreferrer"`.

## Backups and background jobs

- Real archives pass ZIP integrity and SHA-256 checks, use the account UID and mode 600, and contain the expected database SQL. The authenticated panel download returns the matching manifest.
- Retention and explicit deletion affect only the selected installation, preserving the second installation under the same account.
- Reloading the browser preserves the running background update. Publishing a new addon code generation preserves the original worker's identity and progress.
- **Stop after current site** completes that site's backup and does not start the next installation.

Updates are tested actions rather than a guarantee that third-party WordPress code cannot fail. A failed selected backup prevents that site's updates; completed actions remain recorded. Unsupported custom WordPress content-directory layouts are reported before changes.

## 0.1.1 regressions

Verified real WordPress inventory with underscore-prefixed main files, spaces and Unicode. A plugin directory named `--all` was passed as a positional plugin identity rather than a bulk-update option.

A dedicated PHP CLI wrapper disabled process functions to reproduce database-export failure. The corrected direct export and actual account-owned database ZIP completed, with valid SQL, the hosting UID and CLI SAPI. Other restrictions remained active, and CLI/FPM php.ini checksums remained unchanged. A real failing mysqli DNS request retained its complete trace while producing a concise database-host diagnosis.

## 0.1.2 native database backups

The VMware Hestia installation exported the two dedicated test account's distinct registered databases through actual `v-dump-database` calls. Both completed with all PHP CLI process functions disabled. Each account-owned `database.zip` contained valid SQL for the expected database, matched its manifest checksum and had mode 600. Private descriptors delivered SQL to the account writers. CLI/FPM configuration checksums remained unchanged. After native installation, an authenticated panel job also completed database-only backups for both installations without running WordPress updates.

Backend regressions cover account ownership, mismatched hosts/ports, explicit sockets, IPv6 and external fallback selection, native process failures, empty exports and exact SQL contents. A native failure never publishes a database ZIP or silently switches to WordPress export. Existing backup-failure tests verify that a failed selected backup prevents site updates and retains completed backup records.

## 0.1.3 preferences and toolbar

Verified the installed native panel in a real browser: Refresh sites and Update selected sites share one row with the update button immediately to the right. Theme updates default to enabled. Changing update choices, backup choices and retention, including rapid checkbox changes, persists to server state and survives page reload. Explicitly disabled theme updates remain disabled. Test preferences were restored afterward; no WordPress update was run. There were no addon JavaScript errors.

The 69 backend tests and seven PHP request checks pass. Preference regressions verify migration from retention-only settings, rejection of invalid values, preservation of preferences when a job uses different temporary options, and unchanged request data when preferences are edited during a job.

## 0.1.4 Activity site counter

A database-only job for the two dedicated VM installations completed through the native panel. Browser inspection confirmed Website 2/2 between Activity and the operation message, including after reload, with no addon JavaScript errors. The 70 backend tests and seven PHP request checks pass. Worker regression checks observe positions 1/2 and 2/2 during plugin-update progress, including a failed first site; a legacy running job also recovers its position from its request and results.
