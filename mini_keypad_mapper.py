#!/usr/bin/env python3
# mini_keypad_mapper_v3_3.py
# Fixes UI freeze when clicking keypad buttons or table rows (Treeview re-entrancy).
#
# Key changes vs v3.2:
# - select_key(code, source): only manipulates Treeview selection if source=="grid"
# - on_tree_select uses _suppress_tree_event to avoid recursive <<TreeviewSelect>> loops
# - Safer callbacks with try/except

import os, json, queue, threading, time, subprocess, select
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Dict, Optional, List

try:
    from evdev import InputDevice, list_devices, ecodes
except Exception as e:
    raise SystemExit("Requires python3-evdev. Install: sudo apt install -y python3-evdev\n" + str(e))

APP_NAME = "Mini Keypad Mapper"
CONFIG_PATH = os.path.expanduser("~/.keymap.json")

# ---------- Key parsing ----------
MOD_MAP = {"CTRL":"ctrl","CONTROL":"ctrl","ALT":"alt","SHIFT":"shift","SUPER":"super","META":"super","WIN":"super"}
KEYSYM_MAP = {
    "TAB":"Tab",
    "RETURN":"Return","ENTER":"Return",
    "ESC":"Escape","ESCAPE":"Escape",
    "SPACE":"space",
    "BACKSPACE":"BackSpace","BKSP":"BackSpace",
    "DELETE":"Delete","DEL":"Delete",
    "INSERT":"Insert","INS":"Insert",
    "HOME":"Home","END":"End",
    "PAGEUP":"Prior","PGUP":"Prior",
    "PAGEDOWN":"Next","PGDN":"Next",
    "LEFT":"Left","RIGHT":"Right","UP":"Up","DOWN":"Down",
    "PRINTSCREEN":"Print","PRTSC":"Print",
    "VOLUMEUP":"XF86AudioRaiseVolume",
    "VOLUMEDOWN":"XF86AudioLowerVolume",
    "MUTE":"XF86AudioMute",
    "PLAY":"XF86AudioPlay",
    "NEXT":"XF86AudioNext",
    "PREV":"XF86AudioPrev",
}
for i in range(1,25):
    KEYSYM_MAP[f"F{i}"]=f"F{i}"

def combo_to_xdotool(combo: str) -> str:
    parts = [p.strip() for p in combo.replace('-', '+').split('+') if p.strip()]
    out = []
    for p in parts:
        u = p.upper()
        if u in MOD_MAP: out.append(MOD_MAP[u])
        elif len(p)==1 and p.isalnum(): out.append(p.lower())
        elif u in KEYSYM_MAP: out.append(KEYSYM_MAP[u])
        else: out.append(p)
    return "+".join(out)

# ---------- Labels & defaults ----------
DEFAULT_LABELS = {
    ecodes.KEY_KP1:"1", ecodes.KEY_KP2:"2", ecodes.KEY_KP3:"3", ecodes.KEY_KP4:"4",
    ecodes.KEY_KP5:"5", ecodes.KEY_KP6:"6", ecodes.KEY_KP7:"7", ecodes.KEY_KP8:"8",
}
SUGGESTED_DEFAULTS = {
    ecodes.KEY_KP1:("combo","Ctrl+Alt+T"),
    ecodes.KEY_KP2:("combo","Super+A"),
    ecodes.KEY_KP3:("combo","Super"),
    ecodes.KEY_KP4:("combo","Super+E"),
    ecodes.KEY_KP5:("combo","Super+Tab"),
    ecodes.KEY_KP6:("combo","Alt+Tab"),
    ecodes.KEY_KP7:("combo","Super+L"),
    ecodes.KEY_KP8:("combo","Super+H"),
}

# ---------- Data ----------
@dataclass
class Action:
    kind: str
    value: str

@dataclass
class Profile:
    device_path: str = ""
    enabled: bool = True
    mapping: Dict[int, Action] = None
    def to_json(self):
        return {"device_path":self.device_path,"enabled":self.enabled,
                "mapping":{str(k):{"kind":v.kind,"value":v.value} for k,v in (self.mapping or {}).items()}}
    @staticmethod
    def from_json(d: dict) -> "Profile":
        path = d.get("device_path",""); enabled=d.get("enabled",True)
        mapping={}
        for k,v in d.get("mapping",{}).items():
            mapping[int(k)]=Action(v["kind"],v["value"])
        if not mapping:
            mapping={k:Action(kind,val) for k,(kind,val) in SUGGESTED_DEFAULTS.items()}
        return Profile(path,enabled,mapping)

# ---------- Listener ----------
class Listener(threading.Thread):
    def __init__(self, device_path: str, q: queue.Queue, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.device_path=device_path; self.q=q; self.stop_evt=stop_evt; self.dev: Optional[InputDevice]=None
    def run(self):
        while not self.stop_evt.is_set():
            try:
                self.dev=InputDevice(self.device_path)
                self.q.put(("status", f"Listening on {self.dev.name} ({self.device_path})"))
                fd=self.dev.fileno()
                while not self.stop_evt.is_set():
                    r,_,_=select.select([fd],[],[],0.25)
                    if not r: continue
                    for ev in self.dev.read():
                        if ev.type==ecodes.EV_KEY:
                            if ev.value==1: self.q.put(("key_down", ev.code))
                            elif ev.value==0: self.q.put(("key_up", ev.code))
            except PermissionError as e:
                self.q.put(("error", f"Permission denied for {self.device_path}. Use sudo or set udev/group permissions.\n{e}")); break
            except FileNotFoundError:
                self.q.put(("error", f"Device not found: {self.device_path}")); break
            except OSError as e:
                self.q.put(("status", f"Device error: {e}. Retrying...")); time.sleep(0.5)
            except Exception as e:
                self.q.put(("error", f"Listener error: {e}")); time.sleep(0.5)
            finally:
                try:
                    if self.dev: self.dev.close()
                except Exception: pass
                self.dev=None
        self.q.put(("status","Listener stopped"))

# ---------- App ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME); self.geometry("980x620"); self.minsize(940,580)
        s=ttk.Style(self); s.theme_use("clam")
        self.configure(bg="#0f172a")
        s.configure("TFrame", background="#0f172a")
        s.configure("Card.TFrame", background="#111827")
        s.configure("TLabel", background="#0f172a", foreground="#e5e7eb")
        s.configure("Muted.TLabel", background="#0f172a", foreground="#94a3b8")
        s.configure("Card.TLabel", background="#111827", foreground="#e5e7eb")
        s.configure("Key.TButton", padding=14, font=("Segoe UI", 13, "bold"))
        s.map("Key.TButton", background=[("!disabled","#1f2937"),("active","#374151")], foreground=[("!disabled","#f8fafc")])
        s.configure("KeyActive.TButton", padding=14, font=("Segoe UI", 13, "bold"), background="#10b981")

        self.q=queue.Queue(maxsize=512); self.stop_evt=threading.Event(); self.listener=None
        self.profile=self.load_profile(); self.mapping=self.profile.mapping
        self.enabled=tk.BooleanVar(value=self.profile.enabled)

        self._suppress_tree_event=False  # guard re-entrancy
        self.build_ui()
        self.after(80, self.process_q)

    def list_all_devices(self) -> List[str]:
        entries=[]
        for p in list_devices():
            try:
                d=InputDevice(p); caps=d.capabilities(); has_keys=(ecodes.EV_KEY in caps)
                entries.append(f"{d.name} [EV_KEY={has_keys}] ({p})"); d.close()
            except PermissionError:
                entries.append(f"<Permission denied> ({p})")
            except Exception as e:
                entries.append(f"<Error {e}> ({p})")
        return entries or ["<No /dev/input/event* devices detected>"]

    def build_ui(self):
        header=ttk.Frame(self); header.pack(fill="x", padx=16, pady=(14,6))
        ttk.Label(header, text=APP_NAME, font=("Segoe UI",16,"bold"), style="TLabel").pack(anchor="w")
        ttk.Label(header, text="2×4 layout. Keys flash on press. Use selector or manual path.", style="Muted.TLabel").pack(anchor="w")

        top=ttk.Frame(self); top.pack(fill="x", padx=16, pady=(0,6))
        ttk.Label(top, text="Device:", style="TLabel").pack(side="left", padx=(0,6))
        self.device_cb=ttk.Combobox(top, values=self.list_all_devices(), state="readonly", width=62); self.device_cb.pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_devices).pack(side="left", padx=6)
        ttk.Button(top, text="Start Selected", command=self.start_selected).pack(side="left", padx=4)
        ttk.Checkbutton(top, text="Enabled", variable=self.enabled, command=self.on_toggle_enabled).pack(side="right")

        manual=ttk.Frame(self); manual.pack(fill="x", padx=16, pady=(0,6))
        ttk.Label(manual, text="Manual path:", style="TLabel").pack(side="left")
        self.path_var=tk.StringVar(value=self.profile.device_path or "")
        ttk.Entry(manual, textvariable=self.path_var, width=48).pack(side="left", padx=6)
        ttk.Button(manual, text="Start Manual", command=self.start_manual).pack(side="left", padx=4)
        ttk.Button(manual, text="Stop", command=self.stop_listener).pack(side="left", padx=4)

        main=ttk.Frame(self); main.pack(fill="both", expand=True, padx=16, pady=12)
        left=ttk.Frame(main, style="Card.TFrame"); left.pack(side="left", fill="both", expand=True, padx=(0,8))
        right=ttk.Frame(main, style="Card.TFrame"); right.pack(side="left", fill="y", padx=(8,0))

        pad=ttk.Frame(left, style="Card.TFrame", padding=14); pad.pack(fill="x")
        ttk.Label(pad, text="Keypad (2×4)", style="Card.TLabel").pack(anchor="w", pady=(0,10))
        grid=ttk.Frame(pad, style="Card.TFrame"); grid.pack()

        rows=[[ecodes.KEY_KP1,ecodes.KEY_KP2,ecodes.KEY_KP3,ecodes.KEY_KP4],
              [ecodes.KEY_KP5,ecodes.KEY_KP6,ecodes.KEY_KP7,ecodes.KEY_KP8]]
        self.key_buttons: Dict[int, ttk.Button]={}
        for row in rows:
            rf=ttk.Frame(grid, style="Card.TFrame"); rf.pack()
            for code in row:
                btn=ttk.Button(rf, text=DEFAULT_LABELS.get(code,str(code)), style="Key.TButton",
                               command=lambda c=code: self.select_key(c, source="grid"))
                btn.pack(side="left", padx=8, pady=8); self.key_buttons[code]=btn

        table=ttk.Frame(left, style="Card.TFrame", padding=(14,10,14,14)); table.pack(fill="both", expand=True)
        self.tree=ttk.Treeview(table, columns=("key","type","value"), show="headings", height=8, selectmode="extended")
        self.tree.heading("key", text="Key"); self.tree.heading("type", text="Type"); self.tree.heading("value", text="Action")
        self.tree.column("key", width=90); self.tree.column("type", width=80); self.tree.column("value", width=440)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        editor=ttk.Frame(right, style="Card.TFrame", padding=14); editor.pack(fill="y")
        ttk.Label(editor, text="Editor", style="Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.var_code=tk.IntVar(value=ecodes.KEY_KP1); self.var_kind=tk.StringVar(value="combo"); self.var_value=tk.StringVar(value="Ctrl+Alt+T")
        ttk.Label(editor, text="Key code:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(8,4))
        ttk.Entry(editor, textvariable=self.var_code, width=12).grid(row=1, column=1, sticky="w", pady=(8,4))
        ttk.Label(editor, text="Type:", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(editor, textvariable=self.var_kind, values=["combo","command"], state="readonly", width=12).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(editor, text="Value:", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(editor, textvariable=self.var_value, width=28).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Button(editor, text="Record from device", command=self.record_key).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8,4))
        ttk.Button(editor, text="Add/Update", command=self.add_update).grid(row=5, column=0, columnspan=2, sticky="we", pady=4)
        ttk.Button(editor, text="Test selected", command=self.test_selected).grid(row=6, column=0, columnspan=2, sticky="we", pady=4)
        ttk.Button(editor, text="Apply GNOME defaults", command=self.apply_defaults).grid(row=7, column=0, columnspan=2, sticky="we", pady=(8,4))
        ttk.Button(editor, text="Delete selected mapping(s)", command=self.delete_selected).grid(row=8, column=0, columnspan=2, sticky="we", pady=4)
        ttk.Button(editor, text="Save", command=self.save_profile).grid(row=9, column=0, columnspan=2, sticky="we", pady=4)
        ttk.Button(editor, text="Load", command=self.load_profile_ui).grid(row=10, column=0, columnspan=2, sticky="we", pady=4)

        self.status=tk.StringVar(value="Ready."); status=ttk.Frame(self); status.pack(fill="x", padx=16, pady=(0,10))
        ttk.Label(status, textvariable=self.status, style="Muted.TLabel").pack(anchor="w")
        self.refresh_table()

    # ---- device selection ----
    def refresh_devices(self):
        try:
            self.device_cb["values"]=self.list_all_devices()
        except Exception as e:
            self.status.set(f"Refresh error: {e}")

    def start_selected(self):
        entry=self.device_cb.get().strip()
        if not entry or "(" not in entry: self.status.set("Pick a device from the list."); return
        path=entry[entry.rfind("(")+1:-1]; self.path_var.set(path); self.start_with_path(path)

    def start_manual(self):
        path=self.path_var.get().strip()
        if not path: messagebox.showerror("Path","Enter a /dev/input/eventX path"); return
        self.start_with_path(path)

    def start_with_path(self, path: str):
        self.profile.device_path=path; self.stop_listener(); self.stop_evt=threading.Event()
        self.listener=Listener(path, self.q, self.stop_evt); self.listener.start(); self.status.set(f"Started on {path}")

    def stop_listener(self):
        if getattr(self,"stop_evt",None): self.stop_evt.set()
        if self.listener and self.listener.is_alive(): self.listener.join(timeout=0.6)
        self.listener=None

    # ---- selection logic (fixed) ----
    def select_key(self, code: int, source: str="grid"):
        # Update editor fields
        try:
            self.var_code.set(code)
            act=self.mapping.get(code)
            if act:
                self.var_kind.set(act.kind); self.var_value.set(act.value)
            if source=="grid":
                # Only when clicking keypad, mirror selection in table
                iid=str(code)
                if iid in self.tree.get_children():
                    self._suppress_tree_event=True
                    try:
                        self.tree.selection_set(iid); self.tree.see(iid)
                    finally:
                        # delay to avoid immediate re-fire
                        self.after(5, lambda: setattr(self, "_suppress_tree_event", False))
        except Exception as e:
            self.status.set(f"select_key error: {e}")

    def on_tree_select(self, _evt):
        if self._suppress_tree_event: return
        try:
            sel=self.tree.selection()
            if not sel: return
            code=int(sel[0])
            # Update only the editor; DO NOT write selection_set here
            self.select_key(code, source="tree")
        except Exception as e:
            self.status.set(f"tree_select error: {e}")

    def on_toggle_enabled(self):
        self.profile.enabled=self.enabled.get()
        self.status.set("Enabled" if self.enabled.get() else "Disabled")

    def apply_defaults(self):
        for k,(kind,val) in SUGGESTED_DEFAULTS.items():
            self.mapping[k]=Action(kind,val)
        self.refresh_table(); self.status.set("Applied GNOME defaults.")

    def add_update(self):
        try:
            code=int(self.var_code.get())
            kind=self.var_kind.get(); val=self.var_value.get().strip()
            if not val: messagebox.showerror("Invalid","Provide combo (Ctrl+Alt+T) or command (firefox)."); return
            self.mapping[code]=Action(kind,val); self.refresh_table(); self.status.set(f"Mapped {code} → {kind}:{val}")
        except Exception as e:
            messagebox.showerror("Add/Update error", str(e))

    def delete_selected(self):
        sels=self.tree.selection()
        if not sels: messagebox.showinfo("Delete","Select one or more rows to delete."); return
        for iid in sels:
            try:
                code=int(iid); self.mapping.pop(code, None)
            except Exception: pass
        self.refresh_table(); self.status.set("Deleted selected mapping(s).")

    def test_selected(self):
        sel=self.tree.selection()
        if not sel: messagebox.showerror("No selection","Select a row."); return
        code=int(sel[0]); act=self.mapping.get(code)
        if act: self.execute(act)

    def refresh_table(self):
        try:
            self.tree.delete(*self.tree.get_children())
            for code, act in sorted(self.mapping.items(), key=lambda x: x[0]):
                label=DEFAULT_LABELS.get(code, f"{code}")
                self.tree.insert("", "end", iid=str(code), values=(label, act.kind, act.value))
        except Exception as e:
            self.status.set(f"refresh_table error: {e}")

    # ---- persistence ----
    def save_profile(self):
        data={"device_path":self.profile.device_path,"enabled":self.enabled.get(),
              "mapping":{str(k):{"kind":v.kind,"value":v.value} for k,v in self.mapping.items()}}
        try:
            with open(CONFIG_PATH,"w",encoding="utf-8") as f: json.dump(data,f,indent=2)
            self.status.set(f"Saved → {CONFIG_PATH}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def load_profile(self) -> Profile:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH,"r",encoding="utf-8") as f: d=json.load(f)
                return Profile.from_json(d)
            except Exception: pass
        return Profile(mapping={k:Action(kind,val) for k,(kind,val) in SUGGESTED_DEFAULTS.items()})

    def load_profile_ui(self):
        p=self.load_profile(); self.profile=p; self.mapping=p.mapping; self.enabled.set(p.enabled)
        if p.device_path: self.path_var.set(p.device_path)
        self.refresh_table(); self.status.set("Profile loaded.")

    # ---- event processing ----
    def record_key(self):
        # Creamos ventana flotante no modal
        self.record_window = tk.Toplevel(self)
        self.record_window.title("Record key")
        self.record_window.geometry("300x80")
        ttk.Label(self.record_window, text="Press a key on your keypad...").pack(expand=True, pady=20)
        self._record = True

    def process_q(self):
        try:
            while True:
                kind, payload=self.q.get_nowait()
                if kind=="status": self.status.set(payload)
                elif kind=="error": messagebox.showerror("Error", payload); self.status.set(payload)
                elif kind=="key_down":
                    code=int(payload);
                    self.flash_button(code, True)
                    if getattr(self,"_record",False):
                        self.var_code.set(code);
                        self._record=False;
                        self.status.set(f"Captured key: {code}")
                        if hasattr(self,"record_window") and self.record_window.winfo_exists():
                            self.record_window.destroy()
                    elif self.enabled.get():
                        act=self.mapping.get(code);
                        if act:
                            self.execute(act)
                elif kind=="key_up":
                    code=int(payload); self.flash_button(code, False)
        except queue.Empty:
            pass
        self.after(60, self.process_q)

    def flash_button(self, code:int, down:bool):
        btn=self.key_buttons.get(code)
        if not btn: return
        try:
            if down: btn.configure(style="KeyActive.TButton")
            else: self.after(120, lambda b=btn: b.configure(style="Key.TButton"))
        except Exception: pass

    # ---- execute ----
    def execute(self, act: Action):
        try:
            if act.kind=="command":
                subprocess.Popen(act.value, shell=True)
##                subprocess.Popen(act.value, shell=True); self.status.set(f"Run: {act.value}")
            elif act.kind=="combo":
                seq=combo_to_xdotool(act.value); subprocess.Popen(["xdotool","key",seq]); self.status.set(f"Combo: {act.value}")
            else:
                messagebox.showerror("Unknown", f"Unknown action kind: {act.kind}")
        except Exception as e:
            messagebox.showerror("Exec error", str(e))

    def destroy(self):
        self.stop_listener(); return super().destroy()

def main():
    app=App(); app.mainloop()

if __name__=="__main__":
    main()
