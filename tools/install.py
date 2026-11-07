#!/usr/bin/python3
"""Install only addon-owned Hestia files; retain private data and running jobs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'src'))
import state
import lifecycle
import hestia

META = json.loads((SOURCE / 'addon.json').read_text())
TARGET = Path('/opt') / META['id']
RELEASES = Path('/opt') / (META['id'] + '.releases')
ROUTE = hestia.ROOT / 'web/plugins' / META['slug']
COMMAND = hestia.ROOT / 'bin' / META['command']
MENU = hestia.ROOT / 'web/js/custom_scripts' / (META['id'] + '.js')
MARKER = '# Managed by ' + META['id']


def owned_directory(path, mode=0o755):
    if path.exists() or path.is_symlink():
        state.trusted(path, True)
        state.trusted(path / '.addon-owner')
        if not (path / '.addon-owner').is_file() or (path / '.addon-owner').read_text() != META['id']:
            raise ValueError('Refusing an unmanaged directory: ' + str(path))
    else:
        path.mkdir(mode=mode)
        (path / '.addon-owner').write_text(META['id'])
        (path / '.addon-owner').chmod(0o644)


def check_file(path, prefix):
    if path.exists() or path.is_symlink():
        state.trusted(path)
        if prefix not in path.read_text():
            raise ValueError('Refusing an unmanaged integration file: ' + str(path))


def install():
    if os.geteuid() != 0 or not (hestia.ROOT / 'web/inc/main.php').is_file():
        raise ValueError('Run the installer as root on a Linux Hestia server')
    panel = __import__('pwd').getpwnam(hestia.PANEL_USER)
    if panel.pw_uid == 0:
        raise ValueError('The native panel must use an unprivileged Unix identity')
    check_file(COMMAND, MARKER)
    check_file(MENU, '// Managed by ' + META['id'])
    ROUTE.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    owned_directory(ROUTE)
    check_file(ROUTE / 'index.php', '// Managed by ' + META['id'])
    state.trusted(COMMAND.parent, True)
    state.trusted(MENU.parent, True)
    owned_directory(RELEASES)
    if TARGET.exists() or TARGET.is_symlink():
        if not TARGET.is_symlink() or TARGET.resolve().parent != RELEASES:
            raise ValueError('Refusing an unmanaged installed-code path')
        state.trusted(TARGET.resolve(), True)
    files = [SOURCE / 'addon.json', SOURCE / 'info.json', SOURCE / 'LICENSE', SOURCE / 'UPSTREAM']
    files += [p for folder in ('src', 'panel') for p in (SOURCE / folder).rglob('*')
              if p.is_file() and p.suffix in ('.py', '.php', '.css', '.js')]
    digest = hashlib.sha256()
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError('Source symlinks cannot be published')
        digest.update(path.relative_to(SOURCE).as_posix().encode() + b'\0' + path.read_bytes())
    generation = RELEASES / digest.hexdigest()
    if not generation.exists():
        staging = Path(tempfile.mkdtemp(prefix='.stage-', dir=RELEASES))
        try:
            for path in files:
                destination = staging / path.relative_to(SOURCE)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                shutil.copyfile(path, destination)
                destination.chmod(0o644)
            (staging / '.addon-owner').write_text(META['id'])
            for path in (staging / 'panel').glob('*.php'):
                subprocess.run([str(hestia.ROOT / 'php/bin/php'), '-l', str(path)], check=True,
                               capture_output=True, text=True)
            staging.chmod(0o755)
            os.replace(staging, generation)
        finally:
            if staging.exists(): shutil.rmtree(staging)
    else:
        owned_directory(generation)
        for path in files:
            destination = generation / path.relative_to(SOURCE)
            state.trusted(destination)
            if destination.read_bytes() != path.read_bytes():
                raise ValueError('Installed code generation does not match its source')
    lifecycle.install()
    # Do not prune old generations: a running job pins its original source.
    temporary = TARGET.with_name('.' + TARGET.name + '.next')
    if temporary.exists() or temporary.is_symlink():
        if not temporary.is_symlink():
            raise ValueError('Unexpected code-publication temporary file')
        temporary.unlink()
    temporary.symlink_to(generation, target_is_directory=True)
    os.replace(temporary, TARGET)
    entry = (generation / 'panel/index.php').read_text().replace('__INSTALL_ROOT__', str(TARGET))
    state.write(ROUTE / 'index.php', entry.encode())
    (ROUTE / 'index.php').chmod(0o644)
    wrapper = '#!/bin/sh\n' + MARKER + '\nexec /usr/bin/python3 -I -B ' + str(TARGET / 'src/addon.py') + ' "$@"\n'
    state.write(COMMAND, wrapper.encode())
    COMMAND.chmod(0o755)
    state.write(MENU, (generation / 'panel/menu.js').read_bytes())
    MENU.chmod(0o644)
    print(json.dumps(dict(ok=True, version=META['version'], panel='/plugins/' + META['slug'] + '/',
                          generation=digest.hexdigest(), data_preserved=True)))


def uninstall():
    import jobs
    with state.locked():
        current = jobs.current()
        if current and current['state'] in ('queued', 'running'):
            raise ValueError('Let the running job finish before uninstalling')
    lifecycle.remove()
    for path, marker in ((COMMAND, MARKER), (MENU, '// Managed by ' + META['id']),
                         (ROUTE / 'index.php', '// Managed by ' + META['id'])):
        check_file(path, marker)
        path.unlink(missing_ok=True)
    # Private packages, backups, history and code generations remain recoverable.
    print(json.dumps(dict(ok=True, data_preserved=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    try:
        (uninstall if args.uninstall else install)()
    except Exception as error:
        print(json.dumps(dict(ok=False, error=str(error))))
        raise SystemExit(1)
