"""Personal premium ZIP storage. All home filesystem access runs as its owner."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import account_backups


def identity(record):
    digest, name = record.get('sha256'), record.get('filename')
    if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
            or not isinstance(name, str) or not name.endswith('.zip') or name in ('.', '..')
            or any(c in '/\\' or ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError('Invalid personal package identity')
    return digest, name


def run(operation, home, records):
    if os.geteuid() == 0 or Path(home) != Path(__import__('pwd').getpwuid(os.geteuid()).pw_dir):
        raise ValueError('Personal libraries require the hosting account identity')
    if operation == 'remove':
        removed, warnings = 0, []
        for record in records:
            digest, name = identity(record)
            try:
                fd = account_backups.open_parts(home, ['.masswpupdate', 'premium', digest])
                try:
                    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    try: account_backups.owned(os.fstat(source))
                    finally: os.close(source)
                    os.unlink(name, dir_fd=fd); os.fsync(fd); removed += 1
                finally: os.close(fd)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as error:
                warnings.append(name + ': ' + str(error))
        return dict(removed=removed, warnings=warnings)
    digest, name = identity(records)
    fd = account_backups.open_parts(home, ['.masswpupdate', 'premium', digest], operation == 'store')
    try:
        if operation == 'store':
            temporary = '.upload-' + secrets.token_hex(16)
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                value, count = hashlib.sha256(), 0
                with os.fdopen(handle, 'wb') as stream:
                    for block in iter(lambda: sys.stdin.buffer.read(1024 * 1024), b''):
                        stream.write(block); value.update(block); count += len(block)
                    stream.flush(); os.fsync(stream.fileno())
                if value.hexdigest() != digest or count != records['bytes']:
                    raise ValueError('Personal package transfer checksum mismatch')
                # A directory entry cannot redirect a write to another file.
                os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd); os.fsync(fd)
            finally:
                try: os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError: pass
            return dict(stored=True)
        if operation != 'read':
            raise ValueError('Invalid personal library operation')
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(handle, 'rb') as stream:
            info = os.fstat(stream.fileno()); account_backups.owned(info)
            if info.st_size != records['bytes']:
                raise ValueError('Personal package size changed; upload the ZIP again')
            value = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
            if value.hexdigest() != digest:
                raise ValueError('Personal package checksum changed; upload the ZIP again')
            stream.seek(0)
            for block in iter(lambda: stream.read(1024 * 1024), b''): sys.stdout.buffer.write(block)
        return None
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4: raise ValueError('Invalid personal library request')
        result = run(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]))
        if result is not None: print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
