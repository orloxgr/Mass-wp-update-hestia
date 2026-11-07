"""Native Hestia inventory and authorization; never execute user-supplied CLI."""
import json
import os
from pathlib import Path
import pwd
import re
import subprocess

import state

ROOT = Path('/usr/local/hestia')
PANEL_USER = 'hestiaweb'
ENV = {'PATH': '/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin',
       'LANG': 'C.UTF-8', 'HESTIA': str(ROOT)}


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('Invalid Hestia account')
    return value


def cli(command, *arguments):
    if command not in ('v-list-users', 'v-list-user', 'v-list-web-domains', 'v-list-web-domain'):
        raise ValueError('Unsupported Hestia discovery command')
    path = ROOT / 'bin' / command
    state.trusted(path)
    result = subprocess.run([str(path), *arguments], env=ENV, capture_output=True,
                            text=True, timeout=None)
    if result.returncode:
        raise ValueError('Hestia ' + command + ' failed: ' + (result.stderr or result.stdout).strip())
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError('Invalid Hestia inventory response')
    return data


def administrator(actor):
    try:
        actor = name(actor)
    except ValueError as error:
        raise PermissionError('Hestia administrator access is required') from error
    row = cli('v-list-user', actor, 'json').get(actor, {})
    if row.get('ROLE') != 'admin' or row.get('SUSPENDED') != 'no':
        raise PermissionError('Hestia administrator access is required')
    return actor


def accounts():
    result = []
    for owner, row in cli('v-list-users', 'json').items():
        name(owner)
        if row.get('SUSPENDED') == 'yes':
            continue
        unix = pwd.getpwnam(owner)
        if unix.pw_uid == 0 or owner == PANEL_USER:
            raise ValueError('A Hestia hosting account must have its own non-root Unix identity')
        result.append(dict(user=owner, homedir=unix.pw_dir, status=False))
    return result


def domains():
    result = []
    for account in accounts():
        owner = account['user']
        for domain, row in cli('v-list-web-domains', owner, 'json').items():
            if row.get('SUSPENDED') == 'yes':
                continue
            # The single-domain CLI resolves CUSTOM_DOCROOT and the actual
            # DOCUMENT_ROOT; never infer targets from legacy home directories.
            details = cli('v-list-web-domain', owner, domain, 'json').get(domain)
            if not isinstance(details, dict) or details.get('SUSPENDED') == 'yes':
                continue
            path = details.get('DOCUMENT_ROOT')
            if not isinstance(path, str) or not path.startswith('/') or '..' in Path(path).parts:
                raise ValueError('Hestia did not return an absolute document root for ' + domain)
            result.append(dict(user=owner, domain=domain, path=str(Path(path)),
                               url=('https://' if details.get('SSL') == 'yes' else 'http://') + domain + '/',
                               php_version=details.get('BACKEND', ''),
                               backend=details.get('BACKEND', '')))
    return result


def php_runtime(template, owner=None, domain=None):
    match = re.fullmatch(r'PHP-([0-9]+)[_.]([0-9]+)', template or '', re.IGNORECASE)
    if match:
        version = match[1] + '.' + match[2]
    else:
        # Custom Hestia templates need not include a PHP version in their name.
        # Read the generated handler rather than choosing the server default.
        versions = set()
        if owner and domain:
            directory = Path(pwd.getpwnam(name(owner)).pw_dir) / 'conf/web' / domain
            for filename in ('apache2.conf', 'apache2.ssl.conf', 'nginx.conf', 'nginx.ssl.conf'):
                path = directory / filename
                if path.is_file():
                    versions.update(re.findall(r'/(?:var/)?run/php/php([0-9]+\.[0-9]+)-fpm', path.read_text()))
        if len(versions) != 1:
            raise ValueError('Cannot identify the active PHP-FPM runtime for ' + (domain or str(template)))
        version = versions.pop()
    path = (Path('/usr/bin') / ('php' + version)).resolve(strict=True)
    state.trusted(path)
    if not os.access(path, os.X_OK):
        raise ValueError('The domain PHP CLI is not executable: ' + str(path))
    return str(path)
