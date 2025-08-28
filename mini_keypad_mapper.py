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

# Icon definitions using Unicode symbols
ICONS = {
    'save': '💾',
    'load': '📂', 
    'add': '➕',
    'delete': '🗑️',
    'test': '▶️',
    'defaults': '⚙️',
    'refresh': '🔄',
    'start': '▶️',
    'stop': '⏹️',
    'record': '🎙️',
    'status_active': '🟢',
    'status_inactive': '🔴',
    'mapped': '●'
}

def create_tooltip(widget, text):
    """Create a tooltip for a widget."""
    def on_enter(event):
        tooltip = tk.Toplevel()
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
        tooltip.configure(bg="#2d3748")
        label = tk.Label(tooltip, text=text, bg="#2d3748", fg="white", 
                        font=("Arial", 9), padx=8, pady=4)
        label.pack()
        widget.tooltip = tooltip
    
    def on_leave(event):
        if hasattr(widget, 'tooltip'):
            widget.tooltip.destroy()
            del widget.tooltip
    
    widget.bind('<Enter>', on_enter)
    widget.bind('<Leave>', on_leave)

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
        self.title(APP_NAME); self.geometry("1200x750"); self.minsize(1140,680)
        s=ttk.Style(self); s.theme_use("clam")
        self.configure(bg="#f8fafc")
        # Clean, flat design with minimal borders
        s.configure("TFrame", background="#f8fafc")
        s.configure("Section.TFrame", background="#f8fafc")  # No borders, just background
        s.configure("TLabel", background="#f8fafc", foreground="#1e293b")
        s.configure("Muted.TLabel", background="#f8fafc", foreground="#64748b")
        s.configure("Title.TLabel", background="#f8fafc", foreground="#0f172a", font=("Segoe UI", 16, "bold"))
        s.configure("SectionTitle.TLabel", background="#f8fafc", foreground="#334155", font=("Segoe UI", 13, "bold"))
        
        # Key buttons with cleaner styling
        s.configure("Key.TButton", padding=16, font=("Segoe UI", 12, "bold"), relief="flat")
        s.map("Key.TButton", background=[("!disabled","#e2e8f0"),("active","#cbd5e1")], foreground=[("!disabled","#334155")])
        s.configure("KeyActive.TButton", padding=16, font=("Segoe UI", 12, "bold"), background="#10b981", relief="flat")
        s.configure("KeyMapped.TButton", padding=16, font=("Segoe UI", 12, "bold"), background="#3b82f6", relief="flat")
        
        # Button hierarchy: Primary, Secondary, Danger
        s.configure("Primary.TButton", padding=(16,10), font=("Segoe UI", 11, "bold"), relief="flat")
        s.map("Primary.TButton", background=[("!disabled","#2563eb"),("active","#1d4ed8")], foreground=[("!disabled","white")])
        
        s.configure("Secondary.TButton", padding=(12,8), font=("Segoe UI", 10), relief="flat")
        s.map("Secondary.TButton", background=[("!disabled","#e2e8f0"),("active","#cbd5e1")], foreground=[("!disabled","#475569")])
        
        s.configure("Success.TButton", padding=(16,10), font=("Segoe UI", 11, "bold"), relief="flat")
        s.map("Success.TButton", background=[("!disabled","#16a34a"),("active","#15803d")], foreground=[("!disabled","white")])
        
        s.configure("Danger.TButton", padding=(12,8), font=("Segoe UI", 10), relief="flat")
        s.map("Danger.TButton", background=[("!disabled","#dc2626"),("active","#b91c1c")], foreground=[("!disabled","white")])

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
        # Clean header without borders
        header=ttk.Frame(self, style="Section.TFrame"); header.pack(fill="x", padx=24, pady=(20,0))
        title_frame=ttk.Frame(header, style="Section.TFrame")
        title_frame.pack(fill="x")
        ttk.Label(title_frame, text=APP_NAME, style="Title.TLabel").pack(side="left")
        
        # Status indicator
        self.status_indicator = ttk.Label(title_frame, text=ICONS['status_inactive'], 
                                        font=("Segoe UI", 16), style="TLabel")
        self.status_indicator.pack(side="right", padx=(0,8))
        create_tooltip(self.status_indicator, "Device status: Red=disconnected, Green=connected")
        
        ttk.Label(header, text="Configure your Mini Keypad with custom actions. Keys flash on press.", 
                 style="Muted.TLabel", font=("Segoe UI", 11)).pack(anchor="w", pady=(8,0))

        # Device Management - Clean layout with more spacing
        toolbar = ttk.Frame(self, style="Section.TFrame")
        toolbar.pack(fill="x", padx=24, pady=(24,0))
        
        # Device selection - simplified layout
        device_section = ttk.Frame(toolbar, style="Section.TFrame")
        device_section.pack(fill="x")
        
        # Top row: Device dropdown and controls with better spacing
        top_row = ttk.Frame(device_section, style="Section.TFrame")
        top_row.pack(fill="x", pady=(0,16))
        
        ttk.Label(top_row, text="Device", style="SectionTitle.TLabel").pack(side="left", padx=(0,12))
        self.device_cb=ttk.Combobox(top_row, values=self.list_all_devices(), state="readonly", width=45)
        self.device_cb.pack(side="left", padx=(0,12))
        create_tooltip(self.device_cb, "Select your keypad device from the detected list")
        
        refresh_btn = ttk.Button(top_row, text=f"{ICONS['refresh']} Refresh", command=self.refresh_devices, style="Secondary.TButton")
        refresh_btn.pack(side="left", padx=(0,12))
        create_tooltip(refresh_btn, "Refresh the list of available input devices")
        
        start_btn = ttk.Button(top_row, text=f"{ICONS['start']} Start", command=self.start_selected, style="Primary.TButton")
        start_btn.pack(side="left", padx=(0,12))
        create_tooltip(start_btn, "Start listening to the selected device")
        
        self.enabled_cb = ttk.Checkbutton(top_row, text="Enabled", variable=self.enabled, command=self.on_toggle_enabled)
        self.enabled_cb.pack(side="right")
        create_tooltip(self.enabled_cb, "Enable/disable key mapping execution")
        
        # Bottom row: Manual path with cleaner spacing
        bottom_row = ttk.Frame(device_section, style="Section.TFrame")
        bottom_row.pack(fill="x")
        
        ttk.Label(bottom_row, text="Manual Path", style="SectionTitle.TLabel").pack(side="left", padx=(0,12))
        self.path_var=tk.StringVar(value=self.profile.device_path or "")
        path_entry = ttk.Entry(bottom_row, textvariable=self.path_var, width=35)
        path_entry.pack(side="left", padx=(0,12))
        create_tooltip(path_entry, "Enter device path manually (e.g., /dev/input/event0)")
        
        manual_start_btn = ttk.Button(bottom_row, text=f"{ICONS['start']} Start", command=self.start_manual, style="Primary.TButton")
        manual_start_btn.pack(side="left", padx=(0,12))
        create_tooltip(manual_start_btn, "Start listening using the manual path")
        
        stop_btn = ttk.Button(bottom_row, text=f"{ICONS['stop']} Stop", command=self.stop_listener, style="Secondary.TButton")
        stop_btn.pack(side="left")
        create_tooltip(stop_btn, "Stop listening to the current device")

        # Subtle separator line
        separator = ttk.Separator(self, orient='horizontal')
        separator.pack(fill="x", padx=24, pady=(24,0))
        
        # Main content area with generous spacing
        main=ttk.Frame(self, style="Section.TFrame"); main.pack(fill="both", expand=True, padx=24, pady=(24,20))
        
        # Left column: Keypad and Mappings with generous spacing
        left=ttk.Frame(main, style="Section.TFrame"); left.pack(side="left", fill="both", expand=True, padx=(0,24))
        
        # Right column: Editor panel
        right=ttk.Frame(main, style="Section.TFrame"); right.pack(side="right", fill="y")

        # Keypad section - clean title and spacing
        keypad_section=ttk.Frame(left, style="Section.TFrame"); keypad_section.pack(fill="x", pady=(0,32))
        
        # Simple section title
        keypad_title=ttk.Frame(keypad_section, style="Section.TFrame")
        keypad_title.pack(fill="x", pady=(0,16))
        ttk.Label(keypad_title, text="Keypad Layout", style="SectionTitle.TLabel").pack(side="left")
        ttk.Label(keypad_title, text="Click to configure • Blue = mapped", 
                 style="Muted.TLabel", font=("Segoe UI", 10)).pack(side="right")
        
        grid=ttk.Frame(keypad_section, style="Section.TFrame"); grid.pack()
        
        # Keypad grid with better spacing
        rows=[[ecodes.KEY_KP1,ecodes.KEY_KP2,ecodes.KEY_KP3,ecodes.KEY_KP4],
              [ecodes.KEY_KP5,ecodes.KEY_KP6,ecodes.KEY_KP7,ecodes.KEY_KP8]]
        self.key_buttons: Dict[int, ttk.Button]={}
        for i, row in enumerate(rows):
            rf=ttk.Frame(grid, style="Section.TFrame"); rf.pack(pady=8)
            for code in row:
                btn=ttk.Button(rf, text=DEFAULT_LABELS.get(code,str(code)), style="Key.TButton",
                               command=lambda c=code: self.select_key(c, source="grid"))
                btn.pack(side="left", padx=10); self.key_buttons[code]=btn
                create_tooltip(btn, f"Configure key {DEFAULT_LABELS.get(code, str(code))} (code: {code})")

        # Mappings table section - clean and spacious
        table_section=ttk.Frame(left, style="Section.TFrame"); table_section.pack(fill="both", expand=True)
        
        # Simple section title with subtle hint
        table_header=ttk.Frame(table_section, style="Section.TFrame")
        table_header.pack(fill="x", pady=(0,16))
        ttk.Label(table_header, text="Key Mappings", style="SectionTitle.TLabel").pack(side="left")
        ttk.Label(table_header, text="Right-click for options", 
                 style="Muted.TLabel", font=("Segoe UI", 10)).pack(side="right")
        
        # Table with clean styling
        table_frame = ttk.Frame(table_section, style="Section.TFrame")
        table_frame.pack(fill="both", expand=True)
        
        self.tree=ttk.Treeview(table_frame, columns=("key","type","value"), show="headings", height=12, selectmode="extended")
        self.tree.heading("key", text="Key"); self.tree.heading("type", text="Type"); self.tree.heading("value", text="Action")
        self.tree.column("key", width=80); self.tree.column("type", width=100); self.tree.column("value", width=400)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        # Bind right-click for context menu
        self.tree.bind("<Button-3>", self.on_right_click)

        # Clean Action Editor - no borders, just content
        editor_panel=ttk.Frame(right, style="Section.TFrame"); editor_panel.pack(fill="both", expand=True)
        
        # Simple section title
        ttk.Label(editor_panel, text="Action Editor", style="SectionTitle.TLabel").pack(anchor="w", pady=(0,20))
        
        # Form fields with clean styling and good spacing
        self.var_code=tk.IntVar(value=ecodes.KEY_KP1); self.var_kind=tk.StringVar(value="combo"); self.var_value=tk.StringVar(value="Ctrl+Alt+T")
        
        # Key Code field
        ttk.Label(editor_panel, text="Key Code", style="TLabel", font=("Segoe UI", 10)).pack(anchor="w", pady=(0,6))
        key_entry = ttk.Entry(editor_panel, textvariable=self.var_code, font=("Consolas", 10))
        key_entry.pack(fill="x", pady=(0,20))
        create_tooltip(key_entry, "The numeric key code from your device")
        
        # Action Type field
        ttk.Label(editor_panel, text="Action Type", style="TLabel", font=("Segoe UI", 10)).pack(anchor="w", pady=(0,6))
        type_combo = ttk.Combobox(editor_panel, textvariable=self.var_kind, values=["combo","command"], state="readonly")
        type_combo.pack(fill="x", pady=(0,20))
        create_tooltip(type_combo, "combo: Key combination (Ctrl+C)\ncommand: System command or app")
        
        # Action Value field
        ttk.Label(editor_panel, text="Action Value", style="TLabel", font=("Segoe UI", 10)).pack(anchor="w", pady=(0,6))
        value_entry = ttk.Entry(editor_panel, textvariable=self.var_value)
        value_entry.pack(fill="x", pady=(0,24))
        create_tooltip(value_entry, "Examples:\n• Combo: Ctrl+Alt+T, Super+L\n• Command: firefox, /path/to/app")
        
        # Record button - utility action
        record_btn = ttk.Button(editor_panel, text=f"{ICONS['record']} Record Key", command=self.record_key, style="Secondary.TButton")
        record_btn.pack(fill="x", pady=(0,20))
        create_tooltip(record_btn, "Press a key on your device to capture its code")
        
        # Thin separator
        ttk.Separator(editor_panel, orient='horizontal').pack(fill="x", pady=(0,20))
        
        # Primary actions - more prominent
        add_btn = ttk.Button(editor_panel, text=f"{ICONS['add']} Add/Update", command=self.add_update, style="Primary.TButton")
        add_btn.pack(fill="x", pady=(0,12))
        create_tooltip(add_btn, "Save the current action configuration")
        
        save_btn = ttk.Button(editor_panel, text=f"{ICONS['save']} Save Profile", command=self.save_profile, style="Success.TButton")
        save_btn.pack(fill="x", pady=(0,20))
        create_tooltip(save_btn, "Save all mappings to configuration file")
        
        # Secondary actions - smaller, less prominent
        test_btn = ttk.Button(editor_panel, text=f"{ICONS['test']} Test", command=self.test_selected, style="Secondary.TButton")
        test_btn.pack(fill="x", pady=(0,8))
        create_tooltip(test_btn, "Execute the selected mapping to test it")
        
        load_btn = ttk.Button(editor_panel, text=f"{ICONS['load']} Load", command=self.load_profile_ui, style="Secondary.TButton")
        load_btn.pack(fill="x", pady=(0,8))
        create_tooltip(load_btn, "Reload mappings from configuration file")
        
        defaults_btn = ttk.Button(editor_panel, text=f"{ICONS['defaults']} Defaults", command=self.apply_defaults, style="Secondary.TButton")
        defaults_btn.pack(fill="x", pady=(0,12))
        create_tooltip(defaults_btn, "Load suggested GNOME desktop shortcuts")
        
        # Danger action - clearly marked
        delete_btn = ttk.Button(editor_panel, text=f"{ICONS['delete']} Delete", command=self.delete_selected, style="Danger.TButton")
        delete_btn.pack(fill="x", pady=(0,8))
        create_tooltip(delete_btn, "Remove selected mappings from the list")

        # Clean status bar - no border, just text
        self.status=tk.StringVar(value="Ready.")
        status_frame=ttk.Frame(self, style="Section.TFrame")
        status_frame.pack(fill="x", padx=24, pady=(16,20))
        
        # Subtle top border for status area
        ttk.Separator(status_frame, orient='horizontal').pack(fill="x", pady=(0,12))
        
        status_label = ttk.Label(status_frame, textvariable=self.status, style="Muted.TLabel", font=("Segoe UI", 10))
        status_label.pack(anchor="w")
        create_tooltip(status_label, "Application status and recent actions")
        self.refresh_table()
        self.setup_context_menu()

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
        self.status_indicator.configure(text=ICONS['status_active'])
        create_tooltip(self.status_indicator, f"Device connected: {path}")

    def stop_listener(self):
        if getattr(self,"stop_evt",None): self.stop_evt.set()
        if self.listener and self.listener.is_alive(): self.listener.join(timeout=0.6)
        self.listener=None
        self.status_indicator.configure(text=ICONS['status_inactive'])
        create_tooltip(self.status_indicator, "Device status: Red=disconnected, Green=connected")

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
        if self.mapping:
            if not messagebox.askyesno("Apply Defaults", 
                                     "This will overwrite existing mappings with GNOME desktop defaults.\n\nContinue?", 
                                     icon="warning"):
                return
        
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
        if not sels: 
            messagebox.showinfo("Delete","Select one or more rows to delete.")
            return
        
        # Confirmation dialog
        count = len(sels)
        key_names = []
        for iid in sels:
            try:
                code = int(iid)
                key_names.append(DEFAULT_LABELS.get(code, str(code)))
            except Exception:
                pass
        
        if count == 1:
            msg = f"Delete mapping for key {key_names[0]}?"
        else:
            msg = f"Delete {count} mappings for keys: {', '.join(key_names)}?"
        
        if not messagebox.askyesno("Confirm Delete", msg, icon="warning"):
            return
        
        for iid in sels:
            try:
                code=int(iid); self.mapping.pop(code, None)
            except Exception: pass
        self.refresh_table(); self.status.set(f"Deleted {count} mapping(s).")

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
            self.update_keypad_indicators()
        except Exception as e:
            self.status.set(f"refresh_table error: {e}")
    
    def update_keypad_indicators(self):
        """Update visual indicators for mapped keys in the keypad grid."""
        for code, btn in self.key_buttons.items():
            if code in self.mapping:
                # Show indicator for mapped keys
                current_text = DEFAULT_LABELS.get(code, str(code))
                btn.configure(text=f"{current_text} {ICONS['mapped']}", style="KeyMapped.TButton")
            else:
                # Reset to default for unmapped keys
                btn.configure(text=DEFAULT_LABELS.get(code, str(code)), style="Key.TButton")

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
                elif kind=="error": 
                    messagebox.showerror("Error", payload); self.status.set(payload)
                    self.status_indicator.configure(text=ICONS['status_inactive'])
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

    def setup_context_menu(self):
        """Set up the right-click context menu for the mappings table."""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label=f"{ICONS['test']} Test Action", command=self.test_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Edit", command=self.edit_from_context)
        self.context_menu.add_command(label=f"{ICONS['delete']} Delete", command=self.delete_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label=f"{ICONS['add']} Add New Mapping", command=self.add_new_mapping)
    
    def on_right_click(self, event):
        """Handle right-click on the mappings table."""
        try:
            # Select the row under the cursor
            item = self.tree.identify_row(event.y)
            if item:
                self.tree.selection_set(item)
                self.tree.focus(item)
                # Update editor fields
                code = int(item)
                self.select_key(code, source="tree")
            
            # Show context menu
            self.context_menu.post(event.x_root, event.y_root)
        except Exception as e:
            self.status.set(f"Context menu error: {e}")
    
    def edit_from_context(self):
        """Start editing the selected mapping (same as clicking in table)."""
        sel = self.tree.selection()
        if sel:
            code = int(sel[0])
            self.select_key(code, source="tree")
            self.status.set(f"Editing key {code}")
    
    def add_new_mapping(self):
        """Clear the editor to add a new mapping."""
        self.var_code.set(ecodes.KEY_KP1)
        self.var_kind.set("combo")
        self.var_value.set("")
        self.status.set("Ready to add new mapping")
    
    def destroy(self):
        self.stop_listener(); return super().destroy()

def main():
    app=App(); app.mainloop()

if __name__=="__main__":
    main()
