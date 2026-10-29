#!/usr/bin/env python3
"""Stop only the recorded Orca CLI; return failure when stop cannot be verified."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

PROC_ROOT = Path('/proc')
RECORD = Path('/home/node/.config/orca-runtime/server-cli.json')
RUNTIME = b'/home/node/.config/orca-runtime/'


def identity(pid):
    proc = PROC_ROOT / str(pid)
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    return fields[19], fields[0], (proc / 'cmdline').read_bytes().split(bytes([0]))


def stop(record=RECORD, timeout=10):
    try:
        data = json.loads(Path(record).read_text())
        pid, expected = int(data['pid']), str(data['start'])
        if pid <= 1 or not expected.isdigit():
            raise ValueError('invalid recorded identity')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'state': 'unverifiable', 'reason': str(exc)}
    try:
        start, state, argv = identity(pid)
        if start != expected or state in ('Z', 'X'):
            return {'ok': True, 'state': 'already_exited'}
        if b'serve' not in argv or not any(RUNTIME in arg for arg in argv):
            return {'ok': False, 'state': 'identity_mismatch'}
        os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        return {'ok': True, 'state': 'already_exited'}
    except OSError as exc:
        return {'ok': False, 'state': 'unverifiable', 'reason': str(exc)}
    deadline = time.monotonic() + timeout
    while True:
        try:
            start, state, _ = identity(pid)
            if start != expected or state in ('Z', 'X'):
                return {'ok': True, 'state': 'stopped'}
        except (FileNotFoundError, ProcessLookupError):
            return {'ok': True, 'state': 'stopped'}
        except OSError as exc:
            return {'ok': False, 'state': 'unverifiable', 'reason': str(exc)}
        if time.monotonic() >= deadline:
            return {'ok': False, 'state': 'stop_timeout', 'pid': pid}
        time.sleep(0.1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, default=RECORD)
    parser.add_argument('--timeout', type=float, default=10)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    result = stop(args.record, args.timeout)
    print(json.dumps(result))
    sys.exit(0 if result['ok'] else 1)
