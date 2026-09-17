#!/usr/bin/env bash
set -eu
[ "$#" -gt 0 ] && [ "$1" = "exec" ] || exit 64
output=""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "--output-last-message" ]; then
        shift
        output="$1"
    fi
    shift
done
case "$FAKE_CODEX_MODE" in
    fail) printf '%s\n' 'fixture: Codex request failed' >&2; exit 23 ;;
    empty) exit 0 ;;
    success) printf '%s\n' 'OK' > "$output" ;;
    *) exit 64 ;;
esac
