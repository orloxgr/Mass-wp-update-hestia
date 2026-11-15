"""Opt-in administrator console progress; never a work deadline or panel output."""
from contextlib import contextmanager
import datetime
import json
import os
import sys
import threading
import time
import traceback

_stream = None
_message = ''
_since = 0
_lock = threading.RLock()


def _write(stream, text):
    try:
        stream.write(text)
        stream.flush()
    except (OSError, ValueError, UnicodeError):
        # Reporting must never turn completed native work into a failure.
        pass


def _emit(message):
    if _stream is None:
        return
    stamp = datetime.datetime.now().astimezone().strftime('%H:%M:%S')
    _write(_stream, '[' + stamp + '] ' + message + '\n')


def stage(message):
    global _message, _since
    with _lock:
        if _stream is None:
            return
        _message, _since = message, time.monotonic()
        _emit(message)


@contextmanager
def reporting(stream=None, interval=10):
    """Emit current-stage heartbeats while the native operation is still running."""
    global _stream, _message, _since
    with _lock:
        previous = (_stream, _message, _since)
        _stream = sys.stderr if stream is None else stream
        _message, _since = 'Starting installer', time.monotonic()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(interval):
            with _lock:
                _emit('Still working (' + str(int(time.monotonic() - _since)) + 's): ' + _message)
    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join()
        with _lock:
            _stream, _message, _since = previous


def _label(key):
    return {'ok': 'Successful', 'error_type': 'Error type', 'stage': 'Last stage',
            'panel': 'Panel URL', 'resumed': 'Resumed interrupted installation',
            'wordpress': 'WordPress protection', 'unsupported': 'Unsupported domains'}.get(
                key, key.replace('_', ' ').capitalize())


def _lines(value, indent='  '):
    """Keep all result details, including unsupported domains, without raw JSON."""
    rows = []
    if isinstance(value, dict):
        for key, item in value.items():
            label = indent + _label(key) + ':'
            if isinstance(item, (dict, list, tuple)) and item:
                rows.append(label)
                rows.extend(_lines(item, indent + '  '))
            else:
                rows.append(label + ' ' + _value(item))
    else:
        for item in value:
            if isinstance(item, (dict, list, tuple)):
                rows.append(indent + '-')
                rows.extend(_lines(item, indent + '  '))
            else:
                rows.append(indent + '- ' + _value(item))
    return rows


def _value(value):
    if value is True:
        return 'Yes'
    if value is False:
        return 'No'
    if value is None or value == '' or value == [] or value == {}:
        return 'None'
    return str(value).replace('\n', '\n    ')


def summary(title, result, elapsed, operation='Installation', stream=None):
    stream = sys.stdout if stream is None else stream
    status = operation + (' completed' if result['ok'] else ' failed')
    heading = title + ' - ' + status
    # ANSI is presentation only, and is never written into redirected logs.
    try:
        terminal = stream.isatty()
    except (AttributeError, OSError, ValueError):
        terminal = False
    if terminal and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb':
        heading = ('\033[32m' if result['ok'] else '\033[31m') + heading + '\033[0m'
    details = {key: value for key, value in result.items() if key != 'ok'}
    _write(stream, '\n' + heading + '\n' + '\n'.join(_lines(details)) +
           '\n  Elapsed: ' + format(elapsed, '.1f') + 's\n\n')


def execute(operation, *, title, version, json_output=False, action='Installation'):
    """Administrator entry point only; panel/cron JSON never passes through here."""
    started = time.monotonic()
    with reporting():
        stage(title + ' ' + version + ' - ' + action.lower())
        try:
            result = operation()
            if not isinstance(result, dict) or result.get('ok') is not True:
                raise RuntimeError('Installer did not return a successful completion result')
            result = {'version': version, **result}
        except Exception as error:
            result = {'ok': False, 'version': version, 'error_type': type(error).__name__,
                      'error': str(error), 'stage': _message}
            # Keep native child diagnostics and the traceback for investigation.
            for name in ('stdout', 'stderr'):
                output = getattr(error, name, None)
                if output:
                    if isinstance(output, bytes):
                        output = output.decode(errors='replace')
                    _write(sys.stderr, name + ':\n' + str(output).rstrip() + '\n')
            _write(sys.stderr, traceback.format_exc())
    if json_output:
        _write(sys.stdout, json.dumps(result) + '\n')
    else:
        summary(title, result, time.monotonic() - started, action)
    return 0 if result['ok'] else 1
