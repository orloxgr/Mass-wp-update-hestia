# Mass WP Update for Hestia

Update WordPress sites from the Hestia administrator panel and keep your premium plugin ZIPs in one private library.

## Updates

1. Click **Refresh sites** to find WordPress installations in active hosting accounts.
2. Select the sites and the actions: **WordPress core**, **plugins**, **premium plugins**, and **themes**.
3. Choose whether to back up **plugins**, **themes**, and the **database**, and how many backup sets to keep per site (1–10, default 1).
4. Click **Update selected sites**.

Sites run one at a time. Selected backups finish before that site's updates begin; a failed backup stops updates for that site. Activity shows completed actions, skipped premium updates, errors, and backup downloads. **Previous updates & backups** keeps earlier results and downloads available. **Stop after current site** lets the current site finish before the next one starts.

Core updates include the WordPress database update, across the network for Multisite. Each row represents one WordPress installation; updates to a Multisite installation affect its shared files and network. Regular plugin updates exclude plugins registered in the premium library. Premium updates use your uploaded packages, apply only to matching installed plugins with an older version, and check their declared WordPress, PHP, and plugin dependencies. Plugins are not activated automatically.

Backups are stored under the hosting account's home, outside its Hestia document roots:

```text
~/.masswpupdate/<site-id>/YYYY/MM/DD/HHMMSS-<job-id>/
    plugins.zip
    themes.zip
    database.zip
    manifest.json
```

Only the selected ZIPs are created. `database.zip` contains `database.sql`; the other ZIPs contain the selected `wp-content/plugins` or `wp-content/themes` directory. Each WordPress installation has a separate site ID, including installations within the same account. Dates use the server's local time. Files belong to the hosting account with permissions 600; backup directories use 700. Backups count toward the account's disk quota. They are not a complete site backup or an automatic rollback.

**Keep latest backups per site** keeps the newest 1–10 backup sets, including the set just created. The choice is remembered for subsequent jobs. Older sets are removed only after every selected backup for that site finishes successfully. A failed backup preserves the previous completed sets and stops that site's updates. Activity reports any files that could not be removed.

Each site row has **Delete backups**, with confirmation for that specific WordPress installation. It removes that site's managed backup sets without touching another installation's backups. Deletion is unavailable while a job is running. Files with unexpected names, ownership, permissions or links are left in place and reported. Download links disappear from job results when their backups are removed by retention or an administrator.

## Premium plugins

Open **Premium plugins** and click **+ Add premium plugins**. Select one or more installable ZIPs supplied by their developers. Files upload one at a time, with progress and a result for each ZIP; a failed file does not stop the rest. Existing library entries are kept until you use **Replace ZIP**. The plugin reads each name and version from its PHP header without executing it, and stores it as `plugin-directory-version.zip` in a root-private directory outside website document roots.

**Replace ZIP** replaces the library's current package for that plugin. It checks the plugin directory and main file against the existing entry. **View sites** shows installed copies and their versions; select the older copies and click **Update selected**. This action uses the backup choices in the Updates tab and updates only that premium plugin.

Uploading or replacing a ZIP never updates a site automatically. Running jobs keep the exact package versions selected when they started. ZIP filenames do not need to include a version. Additional premium plugins can be added at any time.

**Delete** removes that plugin from the premium library and deletes its uploaded ZIP versions after confirmation. Installed plugins on sites and site backups are kept. Deletion is unavailable while an update job is using the library.

Upload an individual installable plugin ZIP rather than a vendor download bundle. ZIPs are checked for unsafe paths, links, duplicate entries, encryption, and integrity. Resource limits are 256 MiB per ZIP, 1 GiB of expanded contents, and 100,000 entries. Licensed packages belong in the private library, not in this public repository.

When a normal plugin update explicitly fails because its license is missing/expired or its update package is unavailable, its installed identity is added automatically as **Awaiting premium ZIP**. Network errors, timeouts and a plain HTTP 403 do not create premium entries. Upload a matching ZIP using **Upload ZIP** or **+ Add premium plugins**, then run the update. A pending entry contains no executable package and cannot be applied until a ZIP is uploaded. Ready packages are never overwritten by these automatic entries.

## Installation

Requires Hestia's Linux administrator panel, Python 3.9+, a working native Hestia PHP installation, and official WP-CLI installed at `/usr/local/bin/wp`, `/usr/bin/wp`, or `/usr/local/lib/wp-cli/wp-cli.phar`. The WP-CLI file and its parent directories must be owned by root and must not be writable by hosting users. Root-managed symlinks to a trusted WP-CLI file are supported. See the [official WP-CLI installation instructions](https://make.wordpress.org/cli/handbook/guides/installing/).

WordPress must use the standard content, plugin, and theme directories. `wp-config.php` may be in the installation directory or its parent within the same hosting account. Installations with custom content directories are reported as unsupported before an update or backup starts.

Run as root on the Hestia server:

```sh
git clone https://github.com/orloxgr/Mass-wp-update-hestia.git /usr/local/src/mass-wp-update-hestia
python3 /usr/local/src/mass-wp-update-hestia/tools/install.py
```

For an existing installation:

```sh
git -C /usr/local/src/mass-wp-update-hestia pull --ff-only
python3 /usr/local/src/mass-wp-update-hestia/tools/install.py
```

Reload the panel and open **Plugins → Mass WP Update** as a Hestia administrator (not while impersonating a hosting user). The direct panel route is `/plugins/mass-wp-update/`. Click **Refresh sites**, add premium ZIPs and choose sites/actions in the two tabs. Hestia itself has no ZIP-upload installer for this addon.

The installer uses only its own CLI wrapper, menu script, panel route, versioned code directory and tmpfiles entry. It does not edit Hestia core, restart shared services or add a sudoers rule. Code updates retain running jobs and all private data. To remove panel integration while preserving packages/backups/history:

```sh
python3 /usr/local/src/mass-wp-update-hestia/tools/install.py --uninstall
```

Let active jobs finish first. Reinstalling restores access to the retained data.

Account and domain discovery uses Hestia's existing CLI and its resolved document roots, including nested installations. Old migration copies elsewhere in account homes are not scanned. Site names in both tabs open the matching site URL in a new tab. SSL domains use HTTPS; other domains use HTTP.

Account and domain discovery uses Hestia's existing CLI. Each WordPress process runs with that hosting account's Unix UID and the domain's native Hestia PHP runtime. Suspended accounts are skipped. Account ownership or unsupported WordPress layouts produce an error instead of falling back to root. WordPress commands, database exports, and file backups never execute as root.

System paths must be owned by UID 0 and must not be writable by other users. Group-writable paths are accepted only for GID 0 when all explicit and primary-group members have UID 0. MySQL/MariaDB client discovery runs only for database exports, so it does not block site discovery or unrelated actions. Rejected paths report the exact component, ownership, permissions, and reason.

The plugin creates its own private data directory, a separate working directory for account processes, and a native-panel request directory under `/run`. A systemd tmpfiles entry recreates that request directory after reboot. No WordPress companion plugin, scheduled update, daemon, sudoers entry, or change to Hestia core files is required. Deactivation stops new jobs and preserves the library and backups; wait for a running job to finish before deactivating.

Background updates have no addon-imposed execution deadline or command-output cutoff; closing the browser does not stop them. Backup output reserves 256 MiB of available filesystem space. A command failure is recorded and stops the remaining actions for that site. Updates already completed on that site remain applied.

Database exports use the selected domain's PHP CLI as the hosting account. If its `disable_functions` configuration disables WP-CLI's process dependencies (`exec`, `proc_open`, `proc_close`, `proc_get_status`), only those functions are restored for that individual database-export invocation. Every other restriction is retained. No PHP configuration file or web/FPM setting is changed.

Failures show a concise cause with expandable **Technical details** retaining the full original output. For example, an unresolvable database hostname points to `DB_HOST` and DNS; it does not make the addon choose a different database or report success.

## Development

Run backend tests as root on a disposable Linux Hestia test installation; they use isolated temporary data and the native `hestiaweb` Unix identity.

```sh
python3 -m unittest discover -s tests -v
/usr/local/hestia/php/bin/php tests/test_panel.php
python3 tools/build.py
```

The builder includes only the plugin's source, license, and documentation. Tests use synthetic ZIPs; premium packages, credentials, backups, and deployment data are excluded.

Author: [Byron Iniotakis](https://www.iniotakis.com). Licensed under GPL-3.0-or-later. See [UPSTREAM](UPSTREAM) for attribution.

This project is an independent third-party integration. It is not affiliated with, endorsed, sponsored, or supported by Hestia. The Hestia name is used only to describe compatibility with the hosting platform.
