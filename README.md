# Share Approvers Group

Shares a group (e.g. **Approvers**) with all **top-level groups** in GitLab Dedicated, or with a single group on an ad hoc basis. Members of the shared group can then be used as **Protected Environment approvers** across the instance.

## How it works

1. Connects to GitLab using `GITLAB_URL` and `GITLAB_TOKEN`.
2. Collects the target groups:
   - all top-level groups (default), or
   - the one group passed with `--group-id`.
3. For each target group it:
   - skips the shared group itself,
   - skips subgroups (only top-level groups are shared),
   - skips groups that already have the share (`ALREADY_SHARED`),
   - otherwise shares the group at the chosen access level.
4. Writes a CSV report and a log file.

The script is idempotent: re-running it only shares with groups that don't already have the share, such as new top-level groups.

## Prerequisites

- Python 3.8+
- `python-gitlab`

```bash
pip install python-gitlab
```

- An **instance admin** personal access token with `api` scope. A non-admin token only sees groups that user can access, so some groups would be missed.

## Setup

```bash
export GITLAB_URL="https://<your-instance>.gitlab-dedicated.com"
export GITLAB_TOKEN="<admin-token>"
```

## Inputs

| Argument | Required | Description |
|---|---|---|
| `--shared-group-id` | Yes | ID of the group to share (Approvers) |
| `--group-id` | No | Share with this one top-level group only |
| `--access-level` | No | `guest`, `reporter`, `developer` (default), `maintainer` |
| `--dry-run` | No | Report what would change without sharing anything |

## Usage

```bash
# Preview first (recommended)
python share_approvers_group.py --shared-group-id 123 --dry-run

# Share with all top-level groups
python share_approvers_group.py --shared-group-id 123

# Share with one group ad hoc
python share_approvers_group.py --shared-group-id 123 --group-id 456

# Use a different access level
python share_approvers_group.py --shared-group-id 123 --access-level reporter
```

## Output

Each run creates two timestamped files in the current directory:

- `share_approvers_report_<timestamp>.csv`: one row per group processed
- `share_approvers_<timestamp>.log`: full run log (also printed to the console)

### CSV columns

| Column | Description |
|---|---|
| `timestamp` | When the group was processed |
| `target_group_id` | ID of the top-level group |
| `target_group_path` | Full path of the top-level group |
| `shared_group_id` | ID of the Approvers group |
| `shared_group_path` | Full path of the Approvers group |
| `access_level` | Role granted (for existing shares, the current role) |
| `status` | See below |
| `message` | Detail or error text |

### Status values

| Status | Meaning |
|---|---|
| `SHARED` | Share created in this run |
| `ALREADY_SHARED` | Share already existed, no change |
| `DRY_RUN` | Would be shared (dry-run mode) |
| `SKIPPED` | Target is the shared group itself, or not a top-level group |
| `FAILED` | API error; see `message` |

## Notes

- **Access scope:** Sharing at the top level gives every Approvers member the chosen role on every subgroup and project under that group. Use the lowest role your protected environment approval rules need.
- **Existing shares:** If a group already has the share at a different access level, the script does not change it. The report shows the current level.
- **Common failure causes:**
  - Group sharing is restricted at the instance level.
  - The Approvers group has "Prevent members from sending invitations to groups outside of this hierarchy" enabled.
  - The token lacks admin rights or `api` scope.
- **New top-level groups:** These are not covered automatically. Re-run the script (or schedule it) to pick them up.
