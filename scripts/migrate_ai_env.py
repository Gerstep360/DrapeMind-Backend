"""Three-way AI defaults migration. Never imports the app or executes .env values."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MANAGED = frozenset({
    "SCOUT_COMPACT_CLARIFICATIONS",
    "AI_CONTEXT_SIZE", "AI_PARALLEL_SLOTS", "AI_THREADS", "AI_MAX_AGENT_STEPS",
    "AI_TURN_TIMEOUT_SECONDS", "AI_TIMEOUT_SECONDS", "AI_MAX_TOKENS",
    "AI_AGENT_MAX_TOKENS", "AI_AGENT_DEADLINE_SECONDS", "AI_FIRST_TOKEN_TIMEOUT_SECONDS",
    "AI_IDLE_TIMEOUT_SECONDS", "AI_STARTUP_TIMEOUT_SECONDS", "AI_TEMPERATURE",
    "AI_RESPONSE_SHORT_TOKENS", "AI_RESPONSE_NORMAL_TOKENS", "AI_RESPONSE_DEEP_TOKENS",
    "SCOUT_THREADS", "SCOUT_CONTEXT_SIZE", "SCOUT_MAX_TOKENS", "SCOUT_MAX_STEPS",
    "SCOUT_TIMEOUT_SECONDS", "SCOUT_TURN_TIMEOUT_SECONDS", "SCOUT_IDLE_TIMEOUT_SECONDS",
})


def parse(text):
    values = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            key, value = match.groups()
            if key in values:
                raise ValueError("Duplicate configuration key: " + key)
            values[key] = value.strip()
    return values


def plain(value):
    if value and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def atomic_write(path, text):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env-migration-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate(path):
    text = path.read_text(encoding="utf-8-sig")
    current = parse(text)
    defaults = parse((ROOT / ".env.example").read_text(encoding="utf-8-sig"))
    baseline_path = path.with_name(path.name + ".ai-defaults.json")
    previous = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    updates = {}
    retained = []
    for key in sorted(MANAGED & defaults.keys()):
        if key not in current or (
            key in previous and plain(current[key]) == plain(previous[key])
        ):
            updates[key] = defaults[key]
        elif plain(current[key]) != plain(defaults[key]):
            retained.append(key)
    lines = text.splitlines()
    updated_lines = []
    remaining = dict(updates)
    for line in lines:
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)=", line)
        key = match.group(1) if match else None
        if key in remaining:
            line = key + "=" + remaining.pop(key)
        updated_lines.append(line)
    updated_lines.extend(key + "=" + value for key, value in remaining.items())
    result = "\n".join(updated_lines) + "\n"
    if result != text:
        backup = path.with_name(path.name + ".before-ai-migration")
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
        atomic_write(path, result)
    # Contains only published tuning defaults, never secret/current account values.
    atomic_write(baseline_path, json.dumps(
        {key: defaults[key] for key in sorted(MANAGED & defaults.keys())}, indent=2
    ) + "\n")
    print("AI_ENV: migrated defaults; personal overrides retained: " + ",".join(retained))


if __name__ == "__main__":
    migrate(Path(sys.argv[1]).resolve())
