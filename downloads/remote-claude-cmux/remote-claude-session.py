#!/usr/bin/env python3
"""Native Claude sessions and narrowly scoped terminal-client cleanup."""
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys

WORKSPACE = "/workspaces/project-a"
CLAUDE = "/home/node/.local/bin/claude"


def cli(*args):
    return subprocess.run(
        ["bash", "-lic", "exec " + shlex.join([CLAUDE, *args])],
        cwd=WORKSPACE, capture_output=True, text=True, timeout=60,
    )


def sessions():
    result = cli("agents", "--json", "--all")
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def create():
    # Explicit --name is a user title and overrides Claude's generated task title.
    # Keep the native session unnamed; this label is only the terminal's initial title.
    result = cli("--bg", "--dangerously-skip-permissions")
    match = re.search(r"backgrounded\s*·\s*([0-9a-f]{8})\b", result.stdout)
    if result.returncode or not match:
        raise RuntimeError("Could not confirm the session ID. Open the session list before trying again.\n" + result.stdout + result.stderr)
    print(match.group(1) + "|远程 Claude · 新会话", flush=True)


def title(short):
    found = next((row for row in sessions() if row.get("id") == short), None)
    if not found:
        raise RuntimeError("Session was not found: " + short)
    # A native display name must not be allowed to inject terminal control bytes.
    print("".join(c for c in (found.get("name") or "远程 Claude") if c.isprintable()))


def cleanup(token, mode, short=None):
    if not re.fullmatch(r"[0-9a-f-]{32,36}", token):
        raise ValueError("Invalid connection token")
    marker = ("CMUX_CLAUDE_CONNECTION=" + token).encode()
    signaled = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            start = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
            argv = (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            if len(argv) < 2 or Path(os.fsdecode(argv[0])).name != "claude":
                continue
            is_client = (mode == "list" and argv[1:] == [b"agents", b"--dangerously-skip-permissions"])
            is_client |= (mode == "attach" and argv[1:] == [b"attach", os.fsencode(short or "")])
            if not is_client or marker not in (proc / "environ").read_bytes().split(b"\0"):
                continue
            # Recheck the process identity immediately before signaling it.
            if (proc / "stat").read_text().rsplit(")", 1)[1].split()[19] != start:
                continue
            os.kill(int(proc.name), signal.SIGTERM)
            signaled.append({"pid": int(proc.name), "procStart": start})
        except (OSError, ProcessLookupError):
            continue
    print(json.dumps({"connection": token, "mode": mode, "session": short,
                      "signaledClients": signaled, "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}))


if __name__ == "__main__":
    try:
        action, *args = sys.argv[1:]
        if action == "create" and not args:
            create()
        elif action == "title" and len(args) == 1:
            title(args[0])
        elif action == "cleanup" and len(args) in (2, 3):
            cleanup(*args)
        else:
            raise ValueError("Unsupported helper command")
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
