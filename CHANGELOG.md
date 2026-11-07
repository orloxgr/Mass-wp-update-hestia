# Changelog

## 0.1.1

- Accept valid WordPress plugin/theme basenames, including leading underscores, spaces and Unicode. Retain rejection of traversal, path separators and control characters; exceptional plugin names cannot be interpreted as WP-CLI options.
- Restore the process functions required by WP-CLI database exports only in the hosting user's individual PHP CLI export process. Preserve other disabled functions and all CLI/FPM configuration files.
- Show concise database and runtime failure causes in site lists and job results. Keep full original output under expandable Technical details, including older saved results.

## 0.1.0

- Initial native Hestia integration with WordPress discovery, per-domain PHP/account execution, updates, account-owned backups, retention and private premium ZIP library.
- Automatically register explicit license/package-unavailable failures as awaiting ZIP, and open site names in a new tab.
