#!/usr/bin/env python3
# mini_keypad_daemon.py
# Minimal background daemon for Mini Keypad
# Reads mappings from JSON and listens the device forever
# Adapted to survive reboots: uses /dev/input/by-id symlink if available

import os, json, subprocess, time, select
from dataclasses import dataclass
from typing import Dict, Optional
from evdev import InputDevice, ecodes

CONFIG_PATH = os.path.expanduser("~/.keymap.json")

@dataclass
class Action:
    kind: str
    value: str

@dataclass
class Profile:
    device_path: str = ""
    enabled: bool = True
    mapping: Dict[int, Action] = None

    @staticmethod
    def from_json(d: dict) -> "Profile":
        path = d.get("device_path", "")
        enabled = d.get("enabled", True)
        mapping = {}
        for k, v in d.get("mapping", {}).items():
            mapping[int(k)] = Action(v["kind"], v["value"])
        return Profile(path, enabled, mapping)

# --- Utils ---
MOD_MAP = {"CTRL":"ctrl","CONTROL":"ctrl","ALT":"alt","SHIFT":"shift","SUPER":"super","META":"super","WIN":"super"}
KEYSYM_MAP = {"TAB":"Tab","RETURN":"Return","ENTER":"Return","ESC":"Escape","ESCAPE":"Escape","SPACE":"space"}
for i in range(1,25):
    KEYSYM_MAP[f"F{i}"] = f"F{i}"

def combo_to_xdotool(combo: str) -> str:
    parts = [p.strip() for p in combo.replace('-', '+').split('+') if p.strip()]
    out = []
    for p in parts:
        u = p.upper()
        if u in MOD_MAP:
            out.append(MOD_MAP[u])
        elif len(p) == 1 and p.isalnum():
            out.append(p.lower())
        elif u in KEYSYM_MAP:
            out.append(KEYSYM_MAP[u])
        else:
            out.append(p)
    return "+".join(out)

def resolve_device_path(path: str) -> Optional[str]:
    """Resolve symlinks like /dev/input/by-id/... to the actual event device."""
    if path.startswith("/dev/input/by-id/"):
        real_path = os.path.realpath(path)
        if os.path.exists(real_path):
            return real_path
        else:
            print(f"[DAEMON] by-id symlink not valid: {path}")
            return None
    elif os.path.exists(path):
        return path
    else:
        return None

def execute(act: Action):
    try:
        if act.kind == "command":
            subprocess.Popen(act.value, shell=True)
            print(f"[DAEMON] Run: {act.value}")
        elif act.kind == "combo":
            seq = combo_to_xdotool(act.value)
            subprocess.Popen(["xdotool", "key", seq])
            print(f"[DAEMON] Combo: {act.value}")
    except Exception as e:
        print(f"[ERROR] {e}")

# --- Main loop ---
def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"No config found at {CONFIG_PATH}")
        return
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        prof = Profile.from_json(json.load(f))

    # resolve device path to ensure stability
    real_path = resolve_device_path(prof.device_path)
    if not real_path:
        print(f"[DAEMON] Device path invalid: {prof.device_path}")
        return

    print(f"[DAEMON] Listening on {real_path}, enabled={prof.enabled}")
    dev = InputDevice(real_path)
    dev.grab()

    try:
        while True:
            r, _, _ = select.select([dev.fileno()], [], [], 0.25)
            if not r:
                continue
            for ev in dev.read():
                if ev.type == ecodes.EV_KEY and ev.value == 1:  # key down
                    act = prof.mapping.get(ev.code)
                    if prof.enabled and act:
                        execute(act)
    except KeyboardInterrupt:
        print("[DAEMON] Stopped by user")
    finally:
        dev.ungrab()
        dev.close()

if __name__ == "__main__":
    main()

