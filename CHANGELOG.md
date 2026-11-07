# Changelog

## 0.1.4

- Show Website N/total between the Activity heading and the current operation. The worker persists the current site position for update and backup jobs, including after refresh, without counting only successful sites.
- Recover the counter for jobs started by earlier plugin versions without interrupting their pinned workers.

## 0.1.3

- Move Update selected sites beside Refresh sites above the site list.
- Enable theme updates by default. Automatically save update, backup and retention choices on the server as controls change; restore explicit choices after reload or a new login.
- Keep saved preferences separate from temporary job options, including premium-only updates. Changing preferences does not alter a running job's request.

## 0.1.2

- Back up databases registered to the site's own Hestia account through native `v-dump-database`, using Hestia's server credentials rather than the application's dump credentials or PHP process functions. Match database name, host and port before choosing the native provider.
- Keep account-owned `database.zip`, private storage, checksums, retention and backup-before-update behavior. SQL passes through an open private descriptor; root never executes WordPress PHP or writes through an account-controlled destination path.
- Preserve WP-CLI export for external or unmatched connections. Retain complete export error output instead of imposing an error-output cutoff or truncating the original cause. Native failures are not retried through the fallback provider.

## 0.1.1

- Accept valid WordPress plugin/theme basenames, including leading underscores, spaces and Unicode. Retain rejection of traversal, path separators and control characters; exceptional plugin names cannot be interpreted as WP-CLI options.
- Restore the process functions required by WP-CLI database exports only in the hosting user's individual PHP CLI export process. Preserve other disabled functions and all CLI/FPM configuration files.
- Show concise database and runtime failure causes in site lists and job results. Keep full original output under expandable Technical details, including older saved results.

## 0.1.0

- Initial native Hestia integration with WordPress discovery, per-domain PHP/account execution, updates, account-owned backups, retention and private premium ZIP library.
- Automatically register explicit license/package-unavailable failures as awaiting ZIP, and open site names in a new tab.
