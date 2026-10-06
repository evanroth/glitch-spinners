#!/usr/bin/env bash
# glitch-spinners: remove the glitch spinner words and go back to Claude Code's defaults.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/evanroth/glitch-spinners/main/uninstall.sh | bash
#
# Deletes "spinnerVerbs" from ~/.claude/settings.json and leaves every other setting alone.
# Backs up the file first. Needs jq.

set -euo pipefail

SETTINGS="${SPINNER_SETTINGS:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json}"

main() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "This needs jq. Install it (macOS: brew install jq; Debian/Ubuntu: sudo apt install jq) and run again." >&2
    exit 1
  fi

  if [[ ! -s "$SETTINGS" ]] || ! jq -e 'has("spinnerVerbs")' "$SETTINGS" >/dev/null 2>&1; then
    if [[ -s "$SETTINGS" ]] && ! jq -e 'type == "object"' "$SETTINGS" >/dev/null 2>&1; then
      echo "$SETTINGS isn't valid JSON, so I left it alone." >&2
      exit 1
    fi
    echo "No spinner words set in $SETTINGS. Nothing to remove."
    exit 0
  fi

  local tmp
  tmp="$(mktemp -d)"
  trap "rm -rf '$tmp'" EXIT

  local backup="$SETTINGS.backup-$(date +%Y%m%d-%H%M%S)"
  cp -p "$SETTINGS" "$backup"
  echo "Backed up your settings to $backup"

  jq 'del(.spinnerVerbs)' "$SETTINGS" > "$tmp/settings.json"
  jq -e 'type == "object"' "$tmp/settings.json" >/dev/null
  cat "$tmp/settings.json" > "$SETTINGS"

  echo "Removed the spinner words. Start a new Claude Code session to get the defaults back."
}

main "$@"
