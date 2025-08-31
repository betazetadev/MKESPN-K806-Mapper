# MKESPN K806 Mapper

A minimalist tool (daemon + UI) to map keys of the MKESPN K806 mini-keyboard on Linux.  
Tested primarily on **Ubuntu 24.04 (GNOME, X11)** with Python 3.12.

This project was created out of necessity: the MKESPN K806 has no reliable Linux support, so this utility lets you map keys via a background daemon and a small Tkinter UI.

## Features

- Persistent key mappings in JSON (`~/.keymap.json`).
- Stable device resolution using `/dev/input/by-id/...` symlinks to survive reboots.
- Lightweight daemon that listens for key events via `evdev` and triggers actions.
- Tkinter UI to detect the device, capture key codes, edit mappings, and test them live.
- Supports:
  - **combo** → executes a keyboard combination via `xdotool`  
  - **command** → runs a shell command (e.g., `firefox`, `google-chrome https://betazeta.dev`)

## Requirements

- Python 3
- `python3-evdev`
- `xdotool` (only works reliably on X11)
- `python3-tk`
- Optional: `jq`, `zenity` for helper scripts

Install on Ubuntu/Debian:

```bash

  sudo apt update
  sudo apt install -y python3 python3-evdev xdotool python3-tk
  
```

## Repository Structure

- `mini_keypad_daemon.py`: background process, listens to device and executes mapped actions.
- `mini_keypad_mapper.py`: Tkinter UI to create, edit, and save mappings.
- Example helper scripts: `show_keymap.sh` to display mappings in a dialog.

## Using the Mapper (UI)

The graphical mapper helps you configure your keypad visually:

1. Run the UI:

```bash
  
  python3 mini_keypad_mapper.py
  
```

2. Select your device from the dropdown list (it should appear as /dev/input/eventXX or /dev/input/by-id/...).

3. Click Record Key and press a key on the mini keypad to capture its event code.

4. Choose the action type:
* combo: enter a key combination (e.g., Ctrl+Alt+T, Super+E)
* command: enter a shell command (e.g., firefox, google-chrome https://betazeta.dev)

5. Save the mapping. It will be written to ~/.keymap.json.

6. Test mappings directly from the UI before saving.

The UI highlights pressed keys and shows which ones have active mappings.

## Configuration

Mappings are stored in `~/.keymap.json`. Example:

```json

    {
      "device_path": "/dev/input/by-id/usb-MKESPN_K806-event-kbd",
      "enabled": true,
      "mapping": {
        "116": { "kind": "combo", "value": "Ctrl+Alt+T" },
        "117": { "kind": "command", "value": "firefox" }
      }
    }
    
```

## Running the Daemon

You can start the daemon manually:

```bash

  python3 mini_keypad_daemon.py
  
```

Or configure it as a **systemd user service** so it runs automatically.

Create `~/.config/systemd/user/mkespn-k806.service` with the following content:

```ini

    [Unit]
    Description=MKESPN K806 Keymap Daemon
    After=graphical-session.target
    
    [Service]
    ExecStart=/usr/bin/python3 /home/USER/path/to/mini_keypad_daemon.py
    Restart=always
    Environment=DISPLAY=:0
    Environment=XAUTHORITY=/home/USER/.Xauthority
    Environment=PATH=/usr/local/bin:/usr/bin:/bin:/home/USER/bin:/home/USER/.local/bin
    
    [Install]
    WantedBy=default.target
    
```

Replace `USER` and adjust the path.

Then enable it:

```bash

    systemctl --user daemon-reload
    systemctl --user enable --now mkespn-k806.service
    
```

Check status:

```bash

    systemctl --user status mkespn-k806.service
    journalctl --user -u mkespn-k806.service -f
    
```

## Notes & Limitations

- The daemon does **not detect hotplug**: if you connect the keypad after login, restart the daemon.
- Requires proper permissions on `/dev/input/event*`.  
  Add your user to the `input` group or create a `udev` rule, e.g.:

```

  SUBSYSTEM=="input", ATTRS{idVendor}=="30fa", ATTRS{idProduct}=="1340", MODE="0666"
  
```

- Tested on Ubuntu GNOME X11; on Wayland `xdotool` is limited.
- No support for controlling LED/backlight of the keypad.

## Roadmap / Ideas

- Support multiple profiles.
- Predefined layouts (selectable profiles).
- Wayland compatibility (alternative to xdotool).
- Auto-detect and reconnect device on hotplug.
- Improved UI/UX with icons and cleaner design.

## License

This project is licensed under the MIT License.

## Contributing

Contributions are welcome!  
Feel free to fork, submit PRs, or open issues if you need support for other devices.
