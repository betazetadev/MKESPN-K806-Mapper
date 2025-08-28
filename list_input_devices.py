#!/usr/bin/env python3
# list_input_devices.py
import os, stat, sys
try:
    from evdev import InputDevice, list_devices, ecodes
except Exception as e:
    print("Requires python3-evdev: sudo apt install -y python3-evdev")
    sys.exit(1)

def mode_str(mode):
    return stat.filemode(mode)

print("Enumerating /dev/input/event* ...\n")
paths = sorted(list_devices())
if not paths:
    print("No input devices found. Are you inside a container/VM without access?")
    sys.exit(0)

for p in paths:
    try:
        st = os.stat(p)
        perms = mode_str(st.st_mode)
        dev = InputDevice(p)
        caps = dev.capabilities(verbose=True)
        has_keys = any(k == ecodes.EV_KEY for k,_ in caps.items())
        print(f"{p}\n  name: {dev.name}\n  phys: {dev.phys}\n  uniq: {dev.uniq}\n  perms: {perms}\n  has EV_KEY: {has_keys}")
        if has_keys:
            keys = caps.get(ecodes.EV_KEY, [])
            # show the first few keycodes
            preview = ", ".join(str(k) for k in list(keys)[:12])
            print(f"  keys preview: {preview}")
        print()
        dev.close()
    except PermissionError as e:
        print(f"{p}\n  <Permission denied> ({e})\n")
    except Exception as e:
        print(f"{p}\n  <Error opening device> {e}\n")
