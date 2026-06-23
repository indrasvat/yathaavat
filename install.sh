#!/bin/sh
# yathaavat installer — POSIX-portable so `curl ... | sh` works under any
# POSIX shell (bash, dash, ash, busybox sh, ksh, zsh).
#
# yathaavat is a visual debugger for Python 3.14+. It installs as a `uv`
# tool from the GitHub source — no PyPI account, no sudo, no build step.
#
# Usage:
#   curl -fsSL https://yathaavat.pages.dev/install | sh
#   curl ... | sh -s -- --version v0.2.0
#   curl ... | sh -s -- --check        # prerequisites only
#   curl ... | sh -s -- --dry-run      # show what would happen
#   curl ... | sh -s -- --uninstall    # remove yathaavat
set -eu

REPO="indrasvat/yathaavat"
REPO_URL="https://github.com/${REPO}"
BINARY="yathaavat"
PYTHON_VERSION="3.14"

# --- Colors (matched to the yathaavat site: cyan signal on ink) ---------------
# POSIX shells lack `$'\033'`; build ESC once via printf and concatenate.
setup_colors() {
    if [ -n "${NO_COLOR:-}" ] || [ ! -t 1 ]; then
        BOLD="" RESET="" ACCENT="" SOFT="" GREEN="" RED="" YELLOW="" TEXT="" DIM=""
        G1="" G2="" G3="" G4="" G5="" G6=""
    else
        ESC=$(printf '\033')
        BOLD="${ESC}[1m"
        RESET="${ESC}[0m"
        ACCENT="${ESC}[38;2;74;168;255m"    # #4aa8ff  signal blue
        SOFT="${ESC}[38;2;139;213;255m"     # #8bd5ff  soft cyan
        GREEN="${ESC}[38;2;74;222;128m"     # #4ade80  ok
        RED="${ESC}[38;2;255;107;107m"      # #ff6b6b  trap
        YELLOW="${ESC}[38;2;242;201;76m"    # #f2c94c  value
        TEXT="${ESC}[38;2;233;238;252m"     # #e9eefc  ink
        DIM="${ESC}[38;2;110;124;154m"      # #6e7c8a  faint
        # Vertical gradient for the wordmark (palest top -> blue bottom).
        G1="${ESC}[38;2;207;234;255m"
        G2="${ESC}[38;2;169;220;255m"
        G3="${ESC}[38;2;139;213;255m"
        G4="${ESC}[38;2;95;188;255m"
        G5="${ESC}[38;2;58;166;255m"
        G6="${ESC}[38;2;43;134;221m"
    fi
}

# --- Banner -------------------------------------------------------------------
# The "yathaavat" wordmark (figlet 'slant'), printed with a top-to-bottom
# cyan gradient. Single-quoted lines keep the backticks/backslashes literal.
banner() {
    # True terminal width via ioctl (stty), ignoring a stale $COLUMNS that
    # ncurses `tput` may honor. Reads /dev/tty so it works under `curl | sh`
    # where stdin is the pipe. Falls back to tput, then 80.
    cols=$(stty size </dev/tty 2>/dev/null | awk '{print $2}')
    case "${cols}" in ''|*[!0-9]*) cols=$(tput cols 2>/dev/null || echo 80) ;; esac
    case "${cols}" in ''|*[!0-9]*) cols=80 ;; esac
    if [ "${cols}" -lt 60 ]; then
        printf '\n  %s%syathaavat%s %s· visual debugger for Python %s%s\n\n' \
            "${BOLD}" "${SOFT}" "${RESET}" "${DIM}" "${PYTHON_VERSION}+" "${RESET}"
        return
    fi
    printf '\n'
    printf '  %s                __  __                            __%s\n'        "${G1}" "${RESET}"
    printf '  %s   __  ______ _/ /_/ /_  ____ _____ __   ______ _/ /_%s\n'       "${G2}" "${RESET}"
    # shellcheck disable=SC2016  # the figlet wordmark contains literal backticks, not expansions
    printf '  %s  / / / / __ `/ __/ __ \/ __ `/ __ `/ | / / __ `/ __/%s\n'       "${G3}" "${RESET}"
    printf '  %s / /_/ / /_/ / /_/ / / / /_/ / /_/ /| |/ / /_/ / /_%s\n'         "${G4}" "${RESET}"
    printf '  %s \__, /\__,_/\__/_/ /_/\__,_/\__,_/ |___/\__,_/\__/%s\n'         "${G5}" "${RESET}"
    printf '  %s/____/%s\n'                                                       "${G6}" "${RESET}"
    printf '\n  %ssee your program as it really runs%s  %s· Python %s+ · MIT%s\n\n' \
        "${SOFT}" "${RESET}" "${DIM}" "${PYTHON_VERSION}" "${RESET}"
}

# --- Logging ------------------------------------------------------------------
info()       { printf '  %s→%s %s%s%s\n' "${ACCENT}" "${RESET}" "${TEXT}" "$1" "${RESET}"; }
success()    { printf '  %s✓%s %s%s%s\n' "${GREEN}" "${RESET}" "${TEXT}" "$1" "${RESET}"; }
warn()       { printf '  %s!%s %s%s%s\n' "${YELLOW}" "${RESET}" "${TEXT}" "$1" "${RESET}"; }
error_exit() { printf '  %s✗%s %s%s%s\n' "${RED}" "${RESET}" "${TEXT}" "$1" "${RESET}" >&2; exit 1; }
step() {
    printf '\n%s%s[%s/%s]%s %s%s%s%s\n' \
        "${BOLD}" "${ACCENT}" "$1" "$2" "${RESET}" "${BOLD}" "${TEXT}" "$3" "${RESET}"
}
# Named 'section' (not 'head') so it never shadows the head(1) coreutil —
# a function named head() silently hijacks `... | head -1` pipelines.
section() {
    printf '\n%s▸%s %s%s%s%s\n' "${ACCENT}" "${RESET}" "${BOLD}" "${TEXT}" "$1" "${RESET}"
}

# --- Argument parsing ---------------------------------------------------------
usage() {
    printf '%s%syathaavat installer%s\n\n' "${BOLD}" "${TEXT}" "${RESET}"
    printf '%sUsage:%s\n' "${DIM}" "${RESET}"
    printf '  curl -fsSL https://yathaavat.pages.dev/install | sh\n'
    printf '  curl ... | sh -s -- [OPTIONS]\n\n'
    printf '%sBy default, installs the latest published release.%s\n\n' "${DIM}" "${RESET}"
    printf '%sOptions:%s\n' "${DIM}" "${RESET}"
    printf '  %s--version VERSION%s  Install a specific tag (e.g. v0.2.0)\n' "${TEXT}" "${RESET}"
    printf '  %s--main%s             Install the latest commit on main (rolling/dev)\n' "${TEXT}" "${RESET}"
    printf '  %s--check%s            Check prerequisites and exit\n' "${TEXT}" "${RESET}"
    printf '  %s--dry-run%s          Show what would happen, change nothing\n' "${TEXT}" "${RESET}"
    printf '  %s--uninstall%s        Remove yathaavat\n' "${TEXT}" "${RESET}"
    printf '  %s--help%s             Show this help\n' "${TEXT}" "${RESET}"
    exit 0
}

parse_args() {
    VERSION=""
    CHECK_ONLY=0
    DRY_RUN=0
    UNINSTALL=0
    USE_MAIN=0
    TARGET_DESC=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --version)
                [ $# -ge 2 ] || error_exit "--version requires a value (e.g. v0.2.0)"
                VERSION="$2"
                shift 2
                ;;
            --main|--dev) USE_MAIN=1; shift ;;
            --check)      CHECK_ONLY=1; shift ;;
            --dry-run)    DRY_RUN=1; shift ;;
            --uninstall)  UNINSTALL=1; shift ;;
            --help|-h)    usage ;;
            *)            error_exit "Unknown option: $1 (use --help for usage)" ;;
        esac
    done
}

# --- Prerequisites ------------------------------------------------------------
# yathaavat needs `uv` (installs the tool + provisions Python 3.14) and `git`
# (the source is a git+ URL). Python 3.14 itself is fetched by uv if absent.
check_prereqs() {
    ok=1

    if command -v uv >/dev/null 2>&1; then
        success "uv $(uv --version 2>/dev/null | awk '{print $2}')"
    else
        warn "uv not found — yathaavat installs as a uv tool"
        info "Install it: ${BOLD}curl -LsSf https://astral.sh/uv/install.sh | sh${RESET}"
        ok=0
    fi

    if command -v git >/dev/null 2>&1; then
        success "git $(git --version 2>/dev/null | awk '{print $3}')"
    else
        warn "git not found — needed to fetch the source"
        info "Install it from https://git-scm.com/downloads"
        ok=0
    fi

    if command -v "python${PYTHON_VERSION}" >/dev/null 2>&1; then
        success "Python ${PYTHON_VERSION} present"
    else
        info "Python ${PYTHON_VERSION} will be provisioned by uv"
    fi

    [ "${ok}" -eq 1 ] || error_exit "Missing prerequisites — install the above and re-run."
}

# --- Python 3.14 --------------------------------------------------------------
ensure_python() {
    if command -v "python${PYTHON_VERSION}" >/dev/null 2>&1 \
        || uv python find "${PYTHON_VERSION}" >/dev/null 2>&1; then
        success "Python ${PYTHON_VERSION} ready"
        return
    fi
    info "Provisioning Python ${PYTHON_VERSION} via uv…"
    if uv python install "${PYTHON_VERSION}" >/dev/null 2>&1; then
        success "Installed Python ${PYTHON_VERSION}"
    else
        warn "Could not pre-provision Python ${PYTHON_VERSION}; uv will retry during install"
    fi
}

# --- Install ------------------------------------------------------------------
# Newest published release tag (vX.Y.Z), resolved via git — no GitHub API
# rate limits, and git is already a prerequisite. Empty if none/offline.
# Filters to strict vMAJOR.MINOR.PATCH tags so a prerelease (e.g.
# v0.10.0-rc.1, which -v:refname can sort ahead of v0.10.0) is never chosen.
resolve_latest_tag() {
    git ls-remote --tags --refs --sort=-v:refname "${REPO_URL}" 'v*' 2>/dev/null \
        | sed -n 's#.*refs/tags/##p' \
        | grep -m1 -E '^v[0-9]+\.[0-9]+\.[0-9]+$'
}

build_source() {
    SOURCE="git+${REPO_URL}"
    if [ -n "${VERSION}" ]; then
        SOURCE="${SOURCE}@${VERSION}"          # explicit tag wins
        TARGET_DESC="${VERSION}"
    elif [ "${USE_MAIN}" -eq 1 ]; then
        TARGET_DESC="main"                     # rolling: latest commit on main
    else
        tag=$(resolve_latest_tag)              # default: newest release tag
        if [ -n "${tag}" ]; then
            SOURCE="${SOURCE}@${tag}"
            TARGET_DESC="${tag}"
        else
            warn "Could not resolve a release tag — falling back to main"
            TARGET_DESC="main"
        fi
    fi
}

do_install() {
    build_source

    reinstall=""
    if uv tool list 2>/dev/null | grep -q "^${BINARY} "; then
        existing=$(uv tool list 2>/dev/null | awk -v b="${BINARY}" '$1 == b {print $2; exit}')
        info "Upgrading existing install (${existing:-unknown} → ${TARGET_DESC})"
        reinstall="--reinstall"
    fi

    log="${TMPDIR_CREATED}/install.log"
    info "Source: ${DIM}${SOURCE}${RESET}"
    # shellcheck disable=SC2086  # reinstall is an intentional word-split flag
    if uv tool install --python "${PYTHON_VERSION}" ${reinstall} "${SOURCE}" >"${log}" 2>&1; then
        success "Installed ${BINARY}"
    else
        printf '\n'
        sed 's/^/    /' "${log}" >&2
        printf '\n'
        error_exit "Installation failed (see output above). Retry: uv tool install --python ${PYTHON_VERSION} ${SOURCE}"
    fi
}

verify() {
    if command -v "${BINARY}" >/dev/null 2>&1; then
        # First invocation of a freshly-installed uv shim can emit one-time
        # setup noise; warm it, then read the version cleanly by pattern.
        "${BINARY}" --version >/dev/null 2>&1 || true
        ver=$("${BINARY}" --version 2>/dev/null | grep -m1 -iE "${BINARY}|[0-9]+\.[0-9]+" || true)
        [ -n "${ver}" ] || ver="${BINARY} (installed)"
        success "Verified: ${DIM}${ver}${RESET}"
        return
    fi
    warn "${BINARY} is installed but not on your PATH yet"
    info "Add uv's tool dir to PATH, then re-open your shell:"
    # shellcheck disable=SC2016  # literal display text, not an expansion
    printf '\n    %sexport PATH="$HOME/.local/bin:$PATH"%s\n' "${DIM}" "${RESET}"
}

# --- Uninstall / dry-run ------------------------------------------------------
do_uninstall() {
    section "Removing ${BINARY}"
    if ! command -v uv >/dev/null 2>&1; then
        error_exit "uv is required to uninstall ${BINARY}, but it was not found on PATH."
    fi
    if uv tool uninstall "${BINARY}" >/dev/null 2>&1; then
        success "Uninstalled ${BINARY}"
    else
        info "${BINARY} was not installed via uv tool"
    fi
    printf '\n'
}

do_dry_run() {
    build_source
    section "Dry run — nothing will change"
    info "Resolved:  ${BOLD}${TARGET_DESC}${RESET}"
    info "Would run: ${BOLD}uv tool install --python ${PYTHON_VERSION} ${SOURCE}${RESET}"
    info "Target:    ${DIM}\$HOME/.local/bin/${BINARY}${RESET}"
    if uv tool list 2>/dev/null | grep -q "^${BINARY} "; then
        info "Would replace the current install (--reinstall)"
    fi
    printf '\n'
    success "Dry run complete — no changes made"
    printf '\n'
}

# --- Post-install -------------------------------------------------------------
post_install() {
    printf '\n  %s✓%s %s%sInstallation complete%s\n\n' "${GREEN}" "${RESET}" "${BOLD}" "${TEXT}" "${RESET}"
    info  "Launch it:   ${BOLD}${BINARY}${RESET}"
    printf '  %s↳%s %sCtrl+R%s launch  %sCtrl+K%s connect  %sCtrl+A%s attach  %sCtrl+P%s palette  %sCtrl+Q%s quit\n' \
        "${DIM}" "${RESET}" \
        "${SOFT}" "${RESET}" "${SOFT}" "${RESET}" "${SOFT}" "${RESET}" "${SOFT}" "${RESET}" "${SOFT}" "${RESET}"
    info  "Docs & demos: ${DIM}${REPO_URL}${RESET}"
    printf '\n'
}

# --- Cleanup ------------------------------------------------------------------
cleanup() {
    [ -z "${TMPDIR_CREATED:-}" ] || rm -rf "${TMPDIR_CREATED}"
}

# --- Main ---------------------------------------------------------------------
main() {
    setup_colors
    parse_args "$@"
    banner

    if [ "${UNINSTALL}" -eq 1 ]; then
        do_uninstall
        exit 0
    fi

    tmpdir=$(mktemp -d -t yathaavat-install.XXXXXX 2>/dev/null || mktemp -d) \
        || error_exit "Could not create a temporary directory"
    TMPDIR_CREATED="${tmpdir}"
    trap cleanup EXIT INT TERM HUP

    if [ "${CHECK_ONLY}" -eq 1 ]; then
        section "Checking prerequisites"
        check_prereqs
        printf '\n'
        success "All prerequisites met"
        printf '\n'
        exit 0
    fi

    if [ "${DRY_RUN}" -eq 1 ]; then
        section "Checking prerequisites"
        check_prereqs
        do_dry_run
        exit 0
    fi

    step 1 4 "Checking prerequisites"
    check_prereqs

    step 2 4 "Preparing Python ${PYTHON_VERSION}"
    ensure_python

    step 3 4 "Installing ${BINARY}"
    do_install

    step 4 4 "Verifying"
    verify

    post_install
}

main "$@"
