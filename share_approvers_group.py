#!/usr/bin/env python3
"""
Share a group (e.g. "Approvers") with all top-level groups in GitLab,
or with a single group ad hoc.

Usage:
    export GITLAB_URL="https://<your-instance>.gitlab-dedicated.com"
    export GITLAB_TOKEN="<admin personal access token with api scope>"

    # Share with ALL top-level groups
    python share_approvers_group.py --shared-group-id 123

    # Share with ONE group only
    python share_approvers_group.py --shared-group-id 123 --group-id 456

    # Preview only, no changes
    python share_approvers_group.py --shared-group-id 123 --dry-run
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime

import gitlab

ACCESS_LEVELS = {"guest": 10, "reporter": 20, "developer": 30, "maintainer": 40}
LEVEL_NAMES = {v: k for k, v in ACCESS_LEVELS.items()}

CSV_FIELDS = [
    "timestamp",
    "target_group_id",
    "target_group_path",
    "shared_group_id",
    "shared_group_path",
    "access_level",
    "status",
    "message",
]


def setup_logging(log_file):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)],
    )


def process_group(gl, shared_group, target_id, access_level, dry_run):
    """Share shared_group with the target group. Returns one CSV row."""
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "target_group_id": target_id,
        "target_group_path": "",
        "shared_group_id": shared_group.id,
        "shared_group_path": shared_group.full_path,
        "access_level": LEVEL_NAMES.get(access_level, access_level),
        "status": "",
        "message": "",
    }

    try:
        group = gl.groups.get(target_id)
        row["target_group_path"] = group.full_path

        if group.id == shared_group.id:
            row["status"], row["message"] = "SKIPPED", "Target is the shared group itself"
        elif group.parent_id:
            row["status"], row["message"] = "SKIPPED", "Not a top-level group"
        else:
            existing = next(
                (s for s in group.shared_with_groups if s["group_id"] == shared_group.id),
                None,
            )
            if existing:
                level = existing["group_access_level"]
                row["access_level"] = LEVEL_NAMES.get(level, level)
                row["status"], row["message"] = "ALREADY_SHARED", "No change"
            elif dry_run:
                row["status"], row["message"] = "DRY_RUN", "Would be shared"
            else:
                group.share(shared_group.id, access_level)
                row["status"], row["message"] = "SHARED", "Shared successfully"

    except gitlab.exceptions.GitlabError as e:
        row["status"], row["message"] = "FAILED", str(e)

    log = logging.error if row["status"] == "FAILED" else logging.info
    log("%s -> %s : %s (%s)", shared_group.full_path,
        row["target_group_path"] or target_id, row["status"], row["message"])
    return row


def main():
    parser = argparse.ArgumentParser(description="Share a group with top-level groups.")
    parser.add_argument("--shared-group-id", type=int, required=True,
                        help="ID of the group to share (e.g. Approvers)")
    parser.add_argument("--group-id", type=int,
                        help="Optional: share with this one top-level group only")
    parser.add_argument("--access-level", default="developer", choices=ACCESS_LEVELS,
                        help="Role the shared group gets (default: developer)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without sharing")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"share_approvers_{ts}.log"
    report_file = f"share_approvers_report_{ts}.csv"
    setup_logging(log_file)

    url, token = os.getenv("GITLAB_URL"), os.getenv("GITLAB_TOKEN")
    if not url or not token:
        logging.error("Set GITLAB_URL and GITLAB_TOKEN environment variables.")
        sys.exit(1)

    gl = gitlab.Gitlab(url, private_token=token)
    gl.auth()
    logging.info("Connected to %s as %s", url, gl.user.username)

    shared_group = gl.groups.get(args.shared_group_id)
    access_level = ACCESS_LEVELS[args.access_level]
    logging.info("Shared group: %s (id=%s), access level: %s, dry-run: %s",
                 shared_group.full_path, shared_group.id, args.access_level, args.dry_run)

    if args.group_id:
        target_ids = [args.group_id]
    else:
        target_ids = [g.id for g in gl.groups.list(top_level_only=True, iterator=True)]
    logging.info("Groups to process: %d", len(target_ids))

    summary = {}
    with open(report_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for target_id in target_ids:
            row = process_group(gl, shared_group, target_id, access_level, args.dry_run)
            writer.writerow(row)
            f.flush()
            summary[row["status"]] = summary.get(row["status"], 0) + 1

    logging.info("Summary: %s", summary)
    logging.info("Report: %s | Log: %s", report_file, log_file)


if __name__ == "__main__":
    main()
