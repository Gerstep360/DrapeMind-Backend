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
        kill -CONT -- "-$ACTIVE_PID" 2>/dev/null || true
        wait "$ACTIVE_PID" 2>/dev/null || true
    fi
    ui_restore; exit 130
}
trap ui_restore EXIT
trap ui_interrupt INT TERM
progress_update() {
    [[ -n "${DRAPE_PROGRESS_FILE:-}" ]] || return 0
    printf '%s:%s:%s\n' "$1" "$2" "$3" >"$DRAPE_PROGRESS_FILE.next"
    mv -f "$DRAPE_PROGRESS_FILE.next" "$DRAPE_PROGRESS_FILE"
    [[ -z "${DRAPE_APT_STATUS_FILE:-}" ]] || : >"$DRAPE_APT_STATUS_FILE"
}
ui_bar() {
    local percent="$1" label="$2" width filled empty
    local columns; columns=$(ui_width)
    label="${label:0:$((columns-6))}"
    width=$((columns - ${#label} - 3)); (( width > 30 )) && width=30; (( width < 1 )) && width=1
    filled=$((percent * width / 100)); empty=$((width-filled))
    printf '['; printf '%*s' "$filled" '' | tr ' ' '#'; printf '%*s' "$empty" '' | tr ' ' '-'; printf '] %s' "$label"
}
ui_step_progress() {
    local phase='En curso' percent='?' detail='Esperando información del proceso' kind package raw record
    if [[ -s "$DRAPE_PROGRESS_FILE" ]]; then IFS=: read -r phase percent detail <"$DRAPE_PROGRESS_FILE" || true; fi
    if [[ -s "$DRAPE_APT_STATUS_FILE" ]]; then
        record=$(tail -n 1 "$DRAPE_APT_STATUS_FILE")
        IFS=: read -r kind package raw detail <<<"$record"
        case "$kind" in
            dlstatus) phase='APT · descarga'; percent="$raw";;
            pmstatus) phase='APT · instalación'; percent="$raw";;
            pmerror|pmconffile|media-change) phase='APT · requiere atención'; percent='?';;
            *) phase='APT'; percent='?'; detail='Esperando el siguiente evento de APT';;
        esac
    fi
    detail=${detail//$'\r'/ }; detail=${detail//$'\e'/}
    local columns; columns=$(ui_width)
    if [[ "$percent" =~ ^[0-9]+([.][0-9]+)?$ ]] && (( ${percent%%.*} <= 100 )); then
        local formatted; printf -v formatted '%.2f%%' "$percent"
        ui_bar "${percent%%.*}" "$formatted"
    else
        printf '%s' 'En curso · porcentaje no disponible'
    fi
    detail="$phase · $detail"
    printf '\n%s' "${detail:0:$((columns-1))}"
}
run_step() {
    local title="$1"; shift
    STEP=$((STEP+1))
    local logfile start=$SECONDS rc=0 frame=0
    logfile=$(mktemp "$DRAPE_LOG_DIR/$(printf '%02d' "$STEP")-XXXXXX.log")
    export DRAPE_PROGRESS_FILE="$logfile.progress" DRAPE_APT_STATUS_FILE="$logfile.apt-status"
    progress_update 'En curso' '?' "$title"
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏') label width
    ui_text '1;36' "[$STEP/$TOTAL] $title"
    printf 'Registro: %s\n' "$logfile"
    printf 'Etapas completadas: %s/%s\n' "$((STEP-1))" "$TOTAL"
    # Cada paso conserva su código de salida. Los logs son privados, sin volcar secretos al TTY.
    # Cada paso y sus hijos tienen un grupo propio, para cancelar también pip/apt/build.
    local had_monitor=false; [[ $- != *m* ]] || had_monitor=true
    set -m
    "$@" </dev/null >"$logfile" 2>&1 & ACTIVE_PID=$!
    $had_monitor || set +m
    local rendered=false stopped=false last='' current state
    $ui_motion && printf '\033[?25l' || true
    while kill -0 "$ACTIVE_PID" 2>/dev/null; do
        state=$(ps -o stat= -p "$ACTIVE_PID" 2>/dev/null || true)
        if [[ "$state" == *T* ]]; then
            printf '\nEl proceso quedó suspendido por la terminal; se detiene para evitar una espera indefinida.\n' >>"$logfile"
            kill -- "-$ACTIVE_PID" 2>/dev/null || true
            kill -CONT -- "-$ACTIVE_PID" 2>/dev/null || true
            stopped=true; break
        fi
        current=$(ui_step_progress)
        if $ui_motion; then
            $rendered && printf '\033[2A' || true
            printf '\r\033[K %s Etapa %s/%s · %ss\n' "${frames[$((frame%10))]}" "$STEP" "$TOTAL" "$((SECONDS-start))"
            printf '\r\033[K%s\n' "${current%%$'\n'*}"
            printf '\r\033[K%s' "${current#*$'\n'}"
            rendered=true
        elif [[ "$current" != "$last" ]]; then
            printf '%s\n' "$current"; last="$current"
        fi
        frame=$((frame+1)); sleep 0.25
    done
    wait "$ACTIVE_PID" || rc=$?
    ACTIVE_PID=''; ui_restore
    $rendered && printf '\n' || true
    if $stopped; then ui_text '31' 'Proceso suspendido: consulta el registro; la instalación no avanzó.'; return 125; fi
    if (( rc != 0 )); then
        ui_text '1;31' "ERROR: $title (salida $rc)"
        printf 'Registro privado: %s\n' "$logfile"
        return "$rc"
    fi
    ui_text '1;32' "OK · $title · $((SECONDS-start))s"
    ui_bar "$((STEP*100/TOTAL))" "Etapas completadas: $STEP/$TOTAL"; printf '\n'
}

run_foreground_step() {
    local title="$1"; shift
    STEP=$((STEP+1))
    ui_text '1;36' "[$STEP/$TOTAL] $title"
    "$@"
    ui_text '1;32' "OK · $title"
    ui_bar "$((STEP*100/TOTAL))" "Etapas completadas: $STEP/$TOTAL"; printf '\n'
}
