#!/bin/bash
# ╭──────────────────────────────────────────────────────────────╮
# │  yathaavat installer                                        │
# │  Terminal-first visual debugger for Python 3.14+            │
# │  No sudo · No PyPI · Installs via uv                        │
# ╰──────────────────────────────────────────────────────────────╯
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/indrasvat/yathaavat/main/install.sh | bash
#   bash install.sh                     # install latest
#   bash install.sh --version v0.1.0    # install specific version
#   bash install.sh --check             # check prerequisites only
#   bash install.sh --uninstall         # remove yathaavat
#
# Prerequisites: uv, python3.14
# Installs via: uv tool install

set -uo pipefail

# ── Colors ──────────────────────────────────────────────────────
if [ -t 1 ]; then
    RST=$'\033[0m'
    DIM=$'\033[2m'
    BOLD=$'\033[1m'
    RED=$'\033[31m'
    CYN=$'\033[36m'
    BGRN=$'\033[92m'
    BCYN=$'\033[96m'
    BYEL=$'\033[93m'
else
    RST="" DIM="" BOLD="" RED="" CYN="" BGRN="" BCYN="" BYEL=""
fi

# ── Box-drawing ─────────────────────────────────────────────────
BW=54

_box_rule() {
    local left="$1" right="$2" fill=""
    local i
    for ((i = 0; i < BW; i++)); do fill="${fill}-"; done
    printf "  %s%s%s%s%s\n" "$CYN" "$left" "$fill" "$right" "$RST"
}

_box_line() {
    local content="$*"
    local plain
    plain="$(printf '%s' "$content" | sed $'s/\033\[[0-9;]*m//g')"
    local dw=${#plain}
    local pad=$((BW - 1 - dw))
    if [ "$pad" -lt 0 ]; then pad=0; fi
    local spaces=""
    local i
    for ((i = 0; i < pad; i++)); do spaces="${spaces} "; done
    printf "  %s|%s %s%s%s|%s\n" "$CYN" "$RST" "$content" "$spaces" "$CYN" "$RST"
}

# ── Logging ─────────────────────────────────────────────────────
_info()  { printf "  %s|%s  %s>%s %s\n" "${DIM}${CYN}" "$RST" "$CYN" "$RST" "$*"; }
_done()  { printf "  %s|%s  %s+%s %s\n" "${DIM}${CYN}" "$RST" "$BGRN" "$RST" "$*"; }
_warn()  { printf "  %s|%s  %s!  %s%s\n" "${DIM}${CYN}" "$RST" "$BYEL" "$*" "$RST"; }
_fail()  { printf "  %s|%s  %sx%s %s\n" "${DIM}${CYN}" "$RST" "$RED" "$RST" "$*"; }
_step()  { printf "  %s|%s  %s>%s %s\n" "${DIM}${CYN}" "$RST" "$BCYN" "$RST" "$*"; }

# ── Configuration ───────────────────────────────────────────────
REPO="indrasvat/yathaavat"
REPO_URL="https://github.com/${REPO}"
VERSION=""
CHECK_ONLY="false"
UNINSTALL="false"

# ── Argument parsing ────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --version|-v)
            shift
            VERSION="${1:?--version requires a tag (e.g. v0.1.0)}"
            ;;
        --check)
            CHECK_ONLY="true"
            ;;
        --uninstall)
            UNINSTALL="true"
            ;;
        --help|-h)
            printf "Usage: %s [--version TAG] [--check] [--uninstall]\n" "$0"
            printf "\n  --version TAG  Install specific version (default: latest)\n"
            printf "  --check        Check prerequisites only\n"
            printf "  --uninstall    Remove yathaavat\n"
            exit 0
            ;;
        *)
            printf "%sUnknown option: %s%s\n" "$RED" "$1" "$RST" >&2
            exit 2
            ;;
    esac
    shift
done

# ── Banner ──────────────────────────────────────────────────────
show_banner() {
    printf "\n"
    _box_rule "+" "+"
    _box_line ""
    _box_line "${BOLD}yathaavat${RST}  ${DIM}(Sanskrit: as it is, truly)${RST}"
    _box_line ""
    _box_line "Terminal-first visual debugger for Python 3.14+"
    _box_line "${DIM}Textual UI  ·  DAP/debugpy  ·  keyboard-first${RST}"
    _box_line ""
    _box_rule "+" "+"
    printf "\n"
}

# ── Prerequisite checks ────────────────────────────────────────
check_prereqs() {
    local ok="true"

    _step "Checking prerequisites..."
    printf "\n"

    # uv
    if command -v uv >/dev/null 2>&1; then
        local uv_ver
        uv_ver="$(uv --version 2>&1 | head -1)"
        _done "uv: ${DIM}${uv_ver}${RST}"
    else
        _fail "uv: not found"
        _info "  Install: ${BOLD}curl -LsSf https://astral.sh/uv/install.sh | sh${RST}"
        ok="false"
    fi

    # Python 3.14
    local py_found="false"
    for py_cmd in python3.14 python3; do
        if command -v "$py_cmd" >/dev/null 2>&1; then
            local py_ver
            py_ver="$("$py_cmd" --version 2>&1 | head -1)"
            if printf '%s' "$py_ver" | grep -q "3\.14"; then
                _done "python: ${DIM}${py_ver}${RST}"
                py_found="true"
                break
            fi
        fi
    done
    if [ "$py_found" = "false" ]; then
        _fail "python 3.14: not found"
        _info "  Install: ${BOLD}uv python install 3.14${RST}"
        ok="false"
    fi

    # git (needed for git+ install)
    if command -v git >/dev/null 2>&1; then
        _done "git: ${DIM}$(git --version 2>&1 | head -1)${RST}"
    else
        _fail "git: not found"
        _info "  Install: https://git-scm.com/downloads"
        ok="false"
    fi

    printf "\n"

    if [ "$ok" = "false" ]; then
        _fail "Prerequisites not met. Fix the above and retry."
        return 1
    fi
    return 0
}

# ── Uninstall ──────────────────────────────────────────────────
do_uninstall() {
    _step "Removing yathaavat..."

    if uv tool uninstall yathaavat 2>/dev/null; then
        _done "Uninstalled yathaavat"
    else
        _info "yathaavat was not installed via uv tool"
    fi

    printf "\n"
    _done "Done."
}

# ── Install ────────────────────────────────────────────────────
do_install() {
    local source="git+${REPO_URL}"
    if [ -n "$VERSION" ]; then
        source="${source}@${VERSION}"
    fi

    # Check for existing installation
    if uv tool list 2>/dev/null | grep -q "^yathaavat"; then
        local existing_ver
        existing_ver="$(uv tool list 2>/dev/null | grep "^yathaavat" | head -1)"
        _info "Replacing existing: ${DIM}${existing_ver}${RST}"
        uv tool uninstall yathaavat >/dev/null 2>&1 || true
    fi

    _step "Installing from ${DIM}${source}${RST}..."
    printf "\n"

    if uv tool install --python python3.14 "$source" 2>&1 | while IFS= read -r line; do
        printf "  %s|%s  %s%s%s\n" "${DIM}${CYN}" "$RST" "$DIM" "$line" "$RST"
    done; then
        printf "\n"
        _done "Installed successfully"
    else
        printf "\n"
        _fail "Installation failed"
        _info "Try manually: ${BOLD}uv tool install --python python3.14 ${source}${RST}"
        return 1
    fi

    # Verify
    if command -v yathaavat >/dev/null 2>&1; then
        local installed_ver
        installed_ver="$(yathaavat --version 2>&1 | head -1)"
        _done "Verified: ${DIM}${installed_ver}${RST}"
    else
        _warn "Binary not in PATH"
        _info "  Run: ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${RST}"
        _info "  Then: ${BOLD}yathaavat --version${RST}"
    fi
}

# ── Post-install ───────────────────────────────────────────────
post_install() {
    printf "\n"
    _box_rule "+" "+"
    _box_line ""
    _box_line "${BGRN}OK${RST} ${BOLD}yathaavat is ready!${RST}"
    _box_line ""
    _box_line "Quick start:"
    _box_line "  ${BOLD}yathaavat${RST}              launch the TUI"
    _box_line "  ${BOLD}yathaavat --version${RST}    show version"
    _box_line ""
    _box_line "Inside the TUI:"
    _box_line "  ${BCYN}Ctrl+R${RST}  launch a Python script"
    _box_line "  ${BCYN}Ctrl+K${RST}  connect to debugpy server"
    _box_line "  ${BCYN}Ctrl+A${RST}  attach to running process"
    _box_line "  ${BCYN}Ctrl+P${RST}  command palette"
    _box_line "  ${BCYN}Ctrl+Q${RST}  quit"
    _box_line ""
    _box_line "${DIM}${REPO_URL}${RST}"
    _box_line ""
    _box_rule "+" "+"
    printf "\n"
}

# ── Main ───────────────────────────────────────────────────────
main() {
    show_banner

    if [ "$UNINSTALL" = "true" ]; then
        do_uninstall
        exit 0
    fi

    if ! check_prereqs; then
        exit 1
    fi

    if [ "$CHECK_ONLY" = "true" ]; then
        _done "All prerequisites met!"
        exit 0
    fi

    do_install || exit 1

    post_install
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]] || [[ -z "${BASH_SOURCE[0]}" ]]; then
    main
fi
