#!/usr/bin/env bash
# Activates worktree run mode in the CURRENT shell. Do not execute — source it:
#     source ./use_worktree.sh
# Overrides the ~/unimate venv activate-time PYTHONPATH (which pins the main
# repo), so `alexa`, `UIUX_FC2`, `shared_utils` etc. import from THIS worktree.
# Undo: open a fresh terminal, or export PYTHONPATH="$_WORKTREE_MAIN_REPO_PYTHONPATH"
_worktree_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export _WORKTREE_MAIN_REPO_PYTHONPATH="${PYTHONPATH:-}"
export PYTHONPATH="$_worktree_dir:$_worktree_dir/UIUX_FC2:${PYTHONPATH:-}"
echo "worktree mode: PYTHONPATH=$PYTHONPATH"
