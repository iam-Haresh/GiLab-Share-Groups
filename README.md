# GitLab Dedicated – Approvers & Protected Environments Scripts

Two independent scripts for setting up deployment approvals across all **top-level groups**:

| Script | Purpose |
|---|---|
| `share_approvers_group.py` | Shares the **Approvers** group with all top-level groups |
| `protect_other_tier.py` | Protects the **`other`** deployment tier on all top-level groups, with Approvers as the approver group |

**Run order:** Run `share_approvers_group.py` first. A group can only be used as an approver where it has been shared.

---

## Common setup

### Prerequisites

- Python 3.8+
- `python-gitlab`

```bash
pip install python-gitlab
```

- An **instance admin** personal access token with `api` scope. A non-admin token only sees groups that user can access, so some groups would be missed.

### Environment variables

```bash
export GITLAB_URL="https://<your-instance>.gitlab-dedicated.com"
export GITLAB_TOKEN="<admin-token>"
export APPROVER_GROUP_ID=123   # used by protect_other_tier.py
```

### Common behaviour (both scripts)

- **Top-level groups only:** Subgroups are skipped, including any subgroup ID passed in `--group-ids`.
- **Targeting:** With no `--group-ids`, the script runs on all top-level groups. With `--group-ids`, it runs only on the listed IDs. Duplicate IDs are ignored, and an ID that doesn't exist is reported as `FAILED` without stopping the run.
- **Idempotent:** Existing shares and protections are detected and left unchanged, so re-running is safe.
- **Dry run:** `--dry-run` shows what would change without changing anything.
- **Output:** Each run creates a timestamped CSV report and a `.log` file in the current directory. The log is also printed to the console.
- **Crash safety:** The CSV is written row by row, so a partial report survives if the run stops midway.

---

## 1. share_approvers_group.py

Shares a group (e.g. Approvers) with every top-level group, or with a specific list of groups.

### Inputs

| Argument | Required | Description |
|---|---|---|
| `--shared-group-id` | Yes | ID of the group to share (Approvers) |
| `--group-ids` | No | Share with these top-level group IDs only (space-separated list) |
| `--access-level` | No | `guest`, `reporter`, `developer` (default), `maintainer` |
| `--dry-run` | No | Preview only |

### Usage

```bash
python share_approvers_group.py --shared-group-id 123 --dry-run
python share_approvers_group.py --shared-group-id 123
python share_approvers_group.py --shared-group-id 123 --group-ids 456 789 1011
python share_approvers_group.py --shared-group-id 123 --access-level reporter
```

### Output

- `share_approvers_report_<timestamp>.csv`
- `share_approvers_<timestamp>.log`

| CSV column | Description |
|---|---|
| `timestamp` | When the group was processed |
| `target_group_id` / `target_group_path` | The top-level group |
| `shared_group_id` / `shared_group_path` | The Approvers group |
| `access_level` | Role granted (for existing shares, the current role) |
| `status` | See below |
| `message` | Detail or error text |

| Status | Meaning |
|---|---|
| `SHARED` | Share created in this run |
| `ALREADY_SHARED` | Share already existed, no change |
| `DRY_RUN` | Would be shared |
| `SKIPPED` | Target is the shared group itself, or not a top-level group |
| `FAILED` | API error; see `message` |

### Where it shows in the UI

- **Each top-level group:** Under **Manage → Members**, Approvers appears on the **Groups** tab and its members appear on the **Members** tab.
- **Approvers group:** The overview page has a **Shared groups** tab that lists every group it has been shared with.

### Notes

- **Direct members only:** Only **direct** members of Approvers get access. Inherited members and subgroup members of Approvers do not, so add every approver directly to the Approvers group.
- **Access scope:** The chosen role applies to every subgroup and project under each top-level group. Use the lowest role your approval rules need.
- **Existing shares:** A share that already exists at a different access level is not changed.
- **Common failures:**
  - Group sharing is restricted at the instance level.
  - Approvers has "Prevent members from sending invitations to groups outside of this hierarchy" enabled.
  - The token lacks admin rights or `api` scope.

---

## 2. protect_other_tier.py

Creates a **group-level protected environment** for the deployment tier `other` on every top-level group. The same approver group is used for all of them.

### Inputs

| Argument | Required | Description |
|---|---|---|
| `--approver-group-id` | Yes* | Approver group ID. *Can be set with the `APPROVER_GROUP_ID` env var instead |
| `--group-ids` | No | Run for these top-level group IDs only (space-separated list) |
| `--exclude` | No | Space-separated group IDs, names or full paths to skip (case-insensitive) |
| `--required-approvals` | No | Approvals needed from the approver group (default `1`) |
| `--deploy-access-level` | No | Role allowed to deploy: `developer` or `maintainer` (default) |
| `--dry-run` | No | Preview only |

### Usage

```bash
# Preview first
python protect_other_tier.py --dry-run

# All top-level groups
python protect_other_tier.py

# Exclude groups (mix of ID, name, full path; quote names with spaces)
python protect_other_tier.py --exclude 456 platform-team "Sandbox Group"

# Specific groups only
python protect_other_tier.py --group-ids 789 790 791

# Override approver group and approvals
python protect_other_tier.py --approver-group-id 123 --required-approvals 2
```

### Output

- `protect_other_tier_report_<timestamp>.csv`
- `protect_other_tier_<timestamp>.log`

| CSV column | Description |
|---|---|
| `timestamp` | When the group was processed |
| `group_id` / `group_name` / `group_path` | The top-level group |
| `environment_tier` | Always `other` |
| `approver_group_id` / `approver_group_path` | The approver group |
| `required_approvals` | Approvals configured |
| `deploy_access_level` | Role allowed to deploy |
| `status` | See below |
| `message` | Detail, existing rules (if already protected), or error text |
| `error_line` | For failures, the line in the script where it failed |

| Status | Meaning |
|---|---|
| `PROTECTED` | Protection created in this run |
| `ALREADY_PROTECTED` | `other` tier already protected. No change; existing rules are shown in `message` |
| `DRY_RUN` | Would be protected |
| `EXCLUDED` | Matched `--exclude` |
| `SKIPPED` | Target is the approver group itself, or not a top-level group |
| `FAILED` | Error; see `message` and `error_line` |

### Error handling

- **Per-group errors:** Errors on one group are logged with the full traceback, and the line in the script where it failed is written to the `error_line` column. The script then continues with the next group.
- **Fatal errors:** Errors such as auth failure or a bad approver group ID stop the script. The failing line is logged as `Script stopped at line N in ...`.

### Notes

- **Existing protections:** If the `other` tier is already protected, the script **does not modify** it. Review `ALREADY_PROTECTED` rows and update those groups manually if needed.
- **Which environments are covered:** Group-level protection applies to environments in all projects under the group whose **deployment tier** is `other`. GitLab assigns a tier from the environment name when it is not set explicitly. Names that don't match a known tier (production, staging, testing, development) become `other`. Set `deployment_tier` in `.gitlab-ci.yml` if you need to be explicit.
- **Approver group must be shared first:** The approver group must be shared with the top-level group (script 1). Otherwise the API rejects the approval rule and the row shows `FAILED`.
- **Viewing in the UI:** Protections appear under **Settings → CI/CD → Protected environments** of each top-level group.
