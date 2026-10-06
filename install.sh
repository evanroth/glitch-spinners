#!/usr/bin/env bash
# glitch-spinners: replace Claude Code's spinner words with glitched, broken-looking text.
# https://github.com/evanroth/glitch-spinners
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/evanroth/glitch-spinners/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --append   # mix in with Claude's own words
#
# Sets "spinnerVerbs" in ~/.claude/settings.json and leaves every other setting alone.
# Backs up the file first. Needs jq.

set -euo pipefail

VERBS_URL="https://raw.githubusercontent.com/evanroth/glitch-spinners/main/spinner-verbs.json"
SETTINGS="${SPINNER_SETTINGS:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json}"

main() {
  local mode="replace"
  case "${1:-}" in
    "") ;;
    --append) mode="append" ;;
    --replace) mode="replace" ;;
    *) echo "Unknown option: $1 (use --append or --replace)" >&2; exit 1 ;;
  esac

  if ! command -v jq >/dev/null 2>&1; then
    echo "This needs jq. Install it (macOS: brew install jq; Debian/Ubuntu: sudo apt install jq) and run again." >&2
    exit 1
  fi

  local tmp
  tmp="$(mktemp -d)"
  trap "rm -rf '$tmp'" EXIT

  # Use the word list next to this script when run from a clone, otherwise download it.
  local here=""
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  fi
  if [[ -n "$here" && -f "$here/spinner-verbs.json" ]]; then
    cp "$here/spinner-verbs.json" "$tmp/verbs.json"
  else
    if ! curl -fsSL "$VERBS_URL" -o "$tmp/verbs.json"; then
      echo "Couldn't download the word list from $VERBS_URL. Nothing was changed." >&2
      exit 1
    fi
  fi
  if ! jq -e '.verbs | type == "array" and length > 0' "$tmp/verbs.json" >/dev/null 2>&1; then
    echo "The word list didn't download properly. Nothing was changed." >&2
    exit 1
  fi

  mkdir -p "$(dirname "$SETTINGS")"
  if [[ -s "$SETTINGS" ]]; then
    if ! jq -e 'type == "object"' "$SETTINGS" >/dev/null 2>&1; then
      echo "$SETTINGS isn't valid JSON, so I left it alone. Fix it and run again." >&2
      exit 1
    fi
    local backup="$SETTINGS.backup-$(date +%Y%m%d-%H%M%S)"
    cp -p "$SETTINGS" "$backup"
    echo "Backed up your settings to $backup"
  else
    echo '{}' > "$SETTINGS"
  fi

  jq --slurpfile v "$tmp/verbs.json" --arg mode "$mode" \
    '.spinnerVerbs = {mode: $mode, verbs: $v[0].verbs}' "$SETTINGS" > "$tmp/settings.json"
  jq -e '.spinnerVerbs.verbs | length > 0' "$tmp/settings.json" >/dev/null
  cat "$tmp/settings.json" > "$SETTINGS"   # write in place, keeping the file's permissions

  local count
  count="$(jq '.spinnerVerbs.verbs | length' "$SETTINGS")"
  echo "Added $count glitch spinner words to $SETTINGS ($mode mode)."
  echo "Start a new Claude Code session to see them."
}

main "$@"
