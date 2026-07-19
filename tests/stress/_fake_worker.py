#!/usr/bin/env python3
"""Fake worker process that exercises the real subprocess contract.

Receives an explicit task/workspace pair, heartbeats periodically, does short
work, and completes via the CLI without an LLM cost.
"""

import json
import argparse
import os
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("workspace")
    args = parser.parse_args()
    tid = args.task_id
    workspace = args.workspace

    # Announce via CLI (goes through real argparse + init_db + etc)
    subprocess.run(
        ["fabric", "kanban", "heartbeat", tid, "--note", "started"],
        check=True, capture_output=True,
    )

    # Simulate work with periodic heartbeats
    for i in range(3):
        time.sleep(0.3)
        subprocess.run(
            ["fabric", "kanban", "heartbeat", tid, "--note", f"progress {i+1}/3"],
            check=True, capture_output=True,
        )

    # Complete with structured handoff
    subprocess.run(
        [
            "fabric", "kanban", "complete", tid,
            "--summary", f"real-subprocess worker finished {tid}",
            "--metadata", json.dumps({
                "workspace": workspace,
                "worker_pid": os.getpid(),
                "iterations": 3,
            }),
        ],
        check=True, capture_output=True,
    )


if __name__ == "__main__":
    main()
