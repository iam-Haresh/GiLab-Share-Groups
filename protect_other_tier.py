#!/usr/bin/env python3
"""
Protect the deployment tier "other" on all top-level groups (group-level
protected environments), with one approver group for all of them.

Usage:
    export GITLAB_URL="https://<your-instance>.gitlab-dedicated.com"
    export GITLAB_TOKEN="<admin personal access token with api scope>"
    export APPROVER_GROUP_ID=123          # or pass --approver-group-id

    # Preview (recommended first)
    python protect_other_tier.py --dry-run

    # All top-level groups
    python protect_other_tier.py

    # Exclude groups by ID, name or full path
    python protect_other_tier.py --exclude 456 platform-team "Sandbox Group"

    # Specific groups only
    python protect_other_tier.py --group-ids 789 790 791
"""

import argparse
import csv
import logging
import os
import sys
import traceback
from datetime import datetime

import gitlab

TIER = "other"
ACCESS_LEVELS = {"developer": 30, "maintainer": 40}
LEVEL_NAMES = {v: k for k, v in ACCESS_LEVELS.items()}

CSV_FIELDS = [
    "timestamp",
    "group_id",
    "group_name",
    "group_path",
    "environment_tier",
    "approver_group_id",
    "approver_group_path",
    "required_approvals",
    "deploy_access_level",
    "status",
    "message",
    "error_line",
]


def setup_logging(log_file):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)],
    )


def error_line(exc):
    """Return the line in THIS script where the error happened."""
    script = os.path.basename(__file__)
    frames = [f for f in traceback.extract_tb(exc.__traceback__)
              if os.path.basename(f.filename) == script]
    if not frames:
        return ""
    f = frames[-1]
    return f"line {f.lineno} in {f.name}(): {f.line}"


def is_excluded(group, excludes):
    values = {str(group.id), group.name.lower(), group.full_path.lower()}
    return any(e.lower() in values for e in excludes)


def get_protected_tier(gl, group_id):
    """Return the existing protected environment for the tier, or None."""
    try:
        return gl.http_get(f"/groups/{group_id}/protected_environments/{TIER}")
    except gitlab.exceptions.GitlabHttpError as e:
        if e.response_code == 404:
            return None
        raise


def process_group(gl, group, approver, args):
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "group_id": group.id,
        "group_name": group.name,
        "group_path": group.full_path,
        "environment_tier": TIER,
        "approver_group_id": approver.id,
        "approver_group_path": approver.full_path,
        "required_approvals": args.required_approvals,
        "deploy_access_level": args.deploy_access_level,
        "status": "",
        "message": "",
        "error_line": "",
    }

    try:
        if group.id == approver.id:
            row["status"], row["message"] = "SKIPPED", "Target is the approver group itself"
        elif group.parent_id:
            row["status"], row["message"] = "SKIPPED", "Not a top-level group"
        elif is_excluded(group, args.exclude):
            row["status"], row["message"] = "EXCLUDED", "Matched --exclude"
        else:
            existing = get_protected_tier(gl, group.id)
            if existing:
                rules = existing.get("approval_rules", [])
                deploy = existing.get("deploy_access_levels", [])
                row["status"] = "ALREADY_PROTECTED"
                row["message"] = (
                    "No change. Existing approval rules: "
                    + "; ".join(f"{r.get('group_id') or r.get('user_id') or r.get('access_level_description')}"
                                f" x{r.get('required_approvals')}" for r in rules)
                    + " | Deploy: "
                    + "; ".join(d.get("access_level_description", "") for d in deploy)
                )
            elif args.dry_run:
                row["status"], row["message"] = "DRY_RUN", "Would be protected"
            else:
                gl.http_post(
                    f"/groups/{group.id}/protected_environments",
                    post_data={
                        "name": TIER,
                        "deploy_access_levels": [
                            {"access_level": ACCESS_LEVELS[args.deploy_access_level]}
                        ],
                        "approval_rules": [
                            {"group_id": approver.id,
                             "required_approvals": args.required_approvals}
                        ],
                    },
                )
                row["status"], row["message"] = "PROTECTED", "Protected successfully"

    except Exception as e:
        row["status"], row["message"] = "FAILED", str(e)
        row["error_line"] = error_line(e)
        logging.exception("Failed for group %s (id=%s) at %s",
                          group.full_path, group.id, row["error_line"])

    if row["status"] != "FAILED":
        logging.info("%s (id=%s): %s - %s", group.full_path, group.id,
                     row["status"], row["message"])
    return row


def main():
    parser = argparse.ArgumentParser(
        description=f'Protect deployment tier "{TIER}" on top-level groups.')
    parser.add_argument("--approver-group-id", type=int,
                        default=os.getenv("APPROVER_GROUP_ID"),
                        help="Approver group ID (default: APPROVER_GROUP_ID env var)")
    parser.add_argument("--group-ids", type=int, nargs="+",
                        help="Run for these top-level group IDs only (space-separated)")
    parser.add_argument("--exclude", nargs="*", default=[],
                        help="Group IDs, names or full paths to skip")
    parser.add_argument("--required-approvals", type=int, default=1,
                        help="Approvals required from the approver group (default: 1)")
    parser.add_argument("--deploy-access-level", default="maintainer",
                        choices=ACCESS_LEVELS,
                        help="Role allowed to deploy (default: maintainer)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without changing anything")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"protect_other_tier_{ts}.log"
    report_file = f"protect_other_tier_report_{ts}.csv"
    setup_logging(log_file)

    if not args.approver_group_id:
        logging.error("Approver group ID missing. Set APPROVER_GROUP_ID or pass --approver-group-id.")
        sys.exit(1)

    url, token = os.getenv("GITLAB_URL"), os.getenv("GITLAB_TOKEN")
    if not url or not token:
        logging.error("Set GITLAB_URL and GITLAB_TOKEN environment variables.")
        sys.exit(1)

    try:
        gl = gitlab.Gitlab(url, private_token=token)
        gl.auth()
        logging.info("Connected to %s as %s", url, gl.user.username)

        approver = gl.groups.get(int(args.approver_group_id))
        logging.info("Approver group: %s (id=%s) | tier: %s | approvals: %s | "
                     "deploy: %s | dry-run: %s | exclude: %s",
                     approver.full_path, approver.id, TIER, args.required_approvals,
                     args.deploy_access_level, args.dry_run, args.exclude)

        groups, not_found = [], []
        if args.group_ids:
            for gid in dict.fromkeys(args.group_ids):  # remove duplicates, keep order
                try:
                    groups.append(gl.groups.get(gid))
                except gitlab.exceptions.GitlabGetError as e:
                    logging.error("Group id=%s not found or not accessible: %s", gid, e)
                    not_found.append((gid, str(e)))
        else:
            groups = list(gl.groups.list(top_level_only=True, iterator=True))
        logging.info("Groups to process: %d", len(groups))

        summary = {}
        with open(report_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for gid, err in not_found:
                writer.writerow({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "group_id": gid, "environment_tier": TIER,
                    "approver_group_id": approver.id,
                    "approver_group_path": approver.full_path,
                    "status": "FAILED", "message": f"Group not found: {err}",
                })
                summary["FAILED"] = summary.get("FAILED", 0) + 1
            for group in groups:
                row = process_group(gl, group, approver, args)
                writer.writerow(row)
                f.flush()
                summary[row["status"]] = summary.get(row["status"], 0) + 1

        logging.info("Summary: %s", summary)
        logging.info("Report: %s | Log: %s", report_file, log_file)

    except Exception as e:
        logging.exception("Script stopped at %s", error_line(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
