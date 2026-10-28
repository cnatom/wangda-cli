#!/usr/bin/env python3
"""One-screen digest of a wangda-cli queue, read from the local snapshot.

Runs `wanda status --json` (a local file read, no browser connection) and prints
queue entries, the current video position with rate, and an ETA for the current
video only. Safe to run while a queue is playing.

Usage:
    python3 summarize.py [--profile PATH] [--bin wanda]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def load(binary: str, profile: str | None) -> dict:
    cmd = [binary, "status", "--json"]
    if profile:
        cmd += ["--profile", profile]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"status failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout)


def fmt(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}m{total % 60:02d}s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default="wanda")
    ap.add_argument("--profile", help="profile recorded in status.config.profile")
    args = ap.parse_args()

    data = load(args.bin, args.profile)
    print(f"run={data.get('run_id')} status={data.get('status')} index={data.get('index')}")
    for i, entry in enumerate(data.get("queue") or []):
        subject = entry.get("url", "").rstrip("/").split("/")[-1]
        print(f"  [{i}] {entry.get('status')}  {subject}  attempts={entry.get('attempts')}")

    progress = data.get("progress") or {}
    video = progress.get("v") or {}
    if video:
        rate = float(video.get("rate") or 1.0)
        remaining = max(0.0, float(video.get("dur") or 0) - float(video.get("cur") or 0))
        print(
            f"course={progress.get('course')} item={progress.get('idx')} "
            f"video={fmt(video.get('cur') or 0)}/{fmt(video.get('dur') or 0)} "
            f"rate={rate} paused={video.get('paused')} video_eta={fmt(remaining / rate)}"
        )
    states = progress.get("stat") or []
    if states:
        print("items: " + " | ".join(states))
    if data.get("worker_pid"):
        print(f"worker_pid={data['worker_pid']}")

    if data.get("status") in {"unconfirmed", "failed", "waiting_login", "interrupted", "paused"}:
        print(f"last_event={data.get('last_event')}")
        print("next: read `wanda logs --tail 20 --json` and explain the state; do not re-queue first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
