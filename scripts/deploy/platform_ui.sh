#!/usr/bin/env bash
# Terminal adaptable: sin secuencias ANSI en pipes y con movimiento opcional.
ui_color=false; ui_motion=false
if [[ -t 1 && "${TERM:-dumb}" != dumb && -z "${NO_COLOR:-}" ]]; then ui_color=true; fi
if [[ -t 1 && "${TERM:-dumb}" != dumb && "${DRAPEMIND_NO_ANIMATION:-0}" != 1 ]]; then ui_motion=true; fi
ui_width() { local n; n=$(tput cols 2>/dev/null || printf 80); (( n > 100 )) && n=100; (( n < 12 )) && n=12; printf '%s' "$n"; }
ui_text() { local color="$1"; shift; if $ui_color; then printf '\033[%sm%s\033[0m\n' "$color" "$*"; else printf '%s\n' "$*"; fi; }
ui_line() { printf '%*s\n' "$(ui_width)" '' | tr ' ' '='; }
ui_header() {
    ui_line; ui_text '1;36' 'DRAPEMIND / Centro de operaciones';
    printf '%s\n' "${DRAPE_ORIGIN:-https://167.86.106.105}${DRAPE_PREFIX:-/DrapeMind}/" | fold -s -w "$(ui_width)"
    printf '%s\n' "${DRAPE_APP_DIR:-/root/app/DrapeMind}" | fold -s -w "$(ui_width)"; ui_line
}
ui_item() { printf ' %2s  %s\n' "$1" "$2" | fold -s -w "$(ui_width)"; }
STEP=0; TOTAL=1; ACTIVE_PID=''
ui_restore() { if $ui_motion; then printf '\r\033[K\033[?25h'; fi; }
ui_interrupt() {
    if [[ -n "$ACTIVE_PID" ]]; then
        kill -- "-$ACTIVE_PID" 2>/dev/null || true
        wait "$ACTIVE_PID" 2>/dev/null || true
    fi
    ui_restore; exit 130
}
trap ui_restore EXIT
trap ui_interrupt INT TERM
run_step() {
    local title="$1"; shift
    STEP=$((STEP+1))
    local logfile start=$SECONDS rc=0 frame=0
    logfile=$(mktemp "$DRAPE_LOG_DIR/$(printf '%02d' "$STEP")-XXXXXX.log")
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏') label width
    ui_text '1;36' "[$STEP/$TOTAL] $title"
    # Cada paso conserva su código de salida. Los logs son privados, sin volcar secretos al TTY.
    # Cada paso y sus hijos tienen un grupo propio, para cancelar también pip/apt/build.
    local had_monitor=false; [[ $- != *m* ]] || had_monitor=true
    set -m
    "$@" >"$logfile" 2>&1 & ACTIVE_PID=$!
    $had_monitor || set +m
    if $ui_motion; then
        printf '\033[?25l'
        while kill -0 "$ACTIVE_PID" 2>/dev/null; do
            width=$(ui_width); label="${title:0:$((width>22 ? width-22 : 4))}"
            printf '\r\033[K %s %s  %ss' "${frames[$((frame%10))]}" "$label" "$((SECONDS-start))"
            frame=$((frame+1)); sleep 0.12
        done
    fi
    wait "$ACTIVE_PID" || rc=$?
    ACTIVE_PID=''; ui_restore
    if (( rc != 0 )); then
        ui_text '1;31' "ERROR: $title (salida $rc)"
        printf 'Registro privado: %s\n' "$logfile"
        return "$rc"
    fi
    ui_text '1;32' "OK · $title · $((SECONDS-start))s"
}
