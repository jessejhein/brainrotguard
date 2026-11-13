#!/usr/bin/env bash
set -euo pipefail

# This wrapper gives the two Codex launch modes we actually need for this repo:
# - `dev` for normal coding work with a safer sandbox
# - `deploy` for host-level operations like Podman and systemd
#
# Keep the paths explicit instead of trying to infer them from the current
# directory. That makes the wrapper predictable when copied to `~/bin`.
REPO_DIR="${HOME}/Projects/brainrotguard.git"
DEPLOY_DIR="${HOME}/data/dockers/brainrotguard"

usage() {
  cat <<'EOF'
Usage:
  run_codex_brainrotguard.sh dev [extra codex args...]
  run_codex_brainrotguard.sh deploy [extra codex args...]

Modes:
  dev
    Safer default for normal coding work.
    - Sandbox: workspace-write
    - Extra writable dir: ~/data/dockers/brainrotguard
    - Approval mode: on-request

  deploy
    For Podman/systemd/admin work on the local machine.
    - Sandbox: danger-full-access
    - Approval mode: on-request

Examples:
  run_codex_brainrotguard.sh dev
  run_codex_brainrotguard.sh deploy
  run_codex_brainrotguard.sh dev --model gpt-5
  run_codex_brainrotguard.sh deploy "Stop the service, back it up, then wait"
EOF
}

# Require an explicit mode so the intent is always visible in shell history.
if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

mode="$1"
shift

# Shared flags for both modes:
# - `--cd` anchors the session in the repo.
# - `--ask-for-approval on-request` keeps Codex from auto-executing risky
#   commands without a checkpoint.
# - `approvals_reviewer="auto_review"` matches the approval pipeline already
#   used in this environment.
common_args=(
  --cd "${REPO_DIR}"
  --ask-for-approval on-request
  --config 'approvals_reviewer="auto_review"'
)

case "${mode}" in
  dev)
    # Normal coding mode:
    # - `workspace-write` is enough for repo edits and most local file work.
    # - `--add-dir` allows the deployment notes/data directory to be edited too
    #   without opening the rest of the machine.
    exec codex \
      "${common_args[@]}" \
      --sandbox workspace-write \
      --add-dir "${DEPLOY_DIR}" \
      "$@"
    ;;
  deploy)
    # Deployment mode:
    # - `danger-full-access` removes sandbox limits so Podman/systemd work can
    #   complete on the real host.
    # - Still keeps approval prompts on-request, so destructive or irreversible
    #   commands do not run silently.
    exec codex \
      "${common_args[@]}" \
      --sandbox danger-full-access \
      "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown mode: ${mode}" >&2
    echo >&2
    usage >&2
    exit 1
    ;;
esac
