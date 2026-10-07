from __future__ import annotations

import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception as exc:
    print("Tkinter is required to run SC CGF Converter.")
    raise

APP_VERSION = "0.3.11"
APP_TITLE = f"SC CC - Star Citizen CGF Converter {APP_VERSION}"
ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "Profiles"
PRESET_DIR = ROOT / "Presets"
MODULE_DIRS = [ROOT / "Modules" / "Stable", ROOT / "Modules" / "Experimental"]
SETTINGS_DIR = ROOT / "Settings"
LOG_DIR = ROOT / "Logs"
DEFAULT_OUTPUT = ROOT / "Output"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
ASSET_DIR = ROOT / "Assets"
APP_ICON_ICO = ASSET_DIR / "SC_CGF_Converter.ico"
APP_ICON_PNG = ASSET_DIR / "SC_CGF_Converter_Icon.png"

OUTPUT_FLAGS = {
    "Preset": None,
    "USDA": "-usda",
    "DAE": "-dae",
    "GLTF": "-gltf",
    "GLB": "-glb",
}
OUTPUT_FLAG_SET = {"-usd", "-usda", "-dae", "-gltf", "-glb", "-obj"}



def hidden_process_kwargs() -> dict:
    """Prevent console windows from appearing for child processes on Windows."""
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    try:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass
    try:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
    except Exception:
        pass
    return kwargs


def windows_desktop_folder() -> Path:
    """Resolve the real Windows Desktop, including redirected/OneDrive desktops."""
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            # CSIDL_DESKTOPDIRECTORY = 0x0010
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Desktop"


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    temp.replace(path)


def win_cmdline(parts: list[str]) -> str:
    return subprocess.list2cmdline([str(x) for x in parts])

def sanitize_listener_text(value: Any) -> str:
    """Escape control bytes that can break Tk/Tcl text insertion.

    Keep normal tabs and printable Unicode. Newlines are handled by the caller.
    Raw converter diagnostics occasionally print bytes from binary files, including
    NUL. Represent those bytes visibly instead of feeding them directly to Tk.
    """
    text_value = str(value)
    out = []
    for ch in text_value:
        code = ord(ch)
        if ch == "\t" or code >= 32:
            out.append(ch)
        else:
            out.append(f"\\x{code:02X}")
    return "".join(out)


HELP_TEXT = 'NORMAL BATCH EXPORT\n1. Browse to cgf-converter.exe, then click Check Converter once.\n2. Game: StarCitizen. Preset: SC_Normal_Batch_USDA. Processor: <None>.\n3. Click Input Folder to choose the root of the assets to process.\n4. Game/Data root: the extracted Data folder containing Objects and Animations.\n5. Choose a separate Output folder.\n6. Keep Batch folder processing, Preserve input folder structure and Collect native outputs on.\n7. Click EXPORT. The status bar shows progress; converter failures are counted.\n\nNAMED FILE PRESETS\n.skin/chr (landing gear, armor, weapons): CHR and SKIN only, with the existing stock -anim preset behavior.\nAnimated Files (.cga, .skin, .chr): CGA, CHR and SKIN. Requests -anim for CGA/CHR; SKIN is included as the paired skinned geometry.\nAll Star Citizen Files: every supported input asset type — CGF, CGA, CHR, SKIN, ANIM and DBA. This does not include textures/XML or unsupported game formats, and does not add decoder support. Individual converter/processor limitations still apply.\n\nNORMAL PRESET\nWrites USDA. CGF and SKIN use geometry export; CHR and CGA request animation using the stock converter. Uses -ut and info logging. Normal folder scans include CGF/CGA/CHR/SKIN; DBA/ANIM are handled separately.\nChoose SC_Static_USDA when you do not want animation. The normal preset is stock animation conversion; decoded DBA animation is a separate workflow below.\n\nFOLDERS\nInput/Ships/Anvil/gear.chr exports under Output/Ships/Anvil. Files at the input root export at the output root. Turn recursive processing off to process the top folder only. A file input always processes one file. Flat output refuses same-stem assets from different folders. Output inside Input is excluded from scanning.\nSome converter versions write beside the source. Collect native outputs copies the resulting files to Output; the source-side files remain.\n\nDECODED DBA ANIMATION\nChoose SC Native Animation Export as Processor. Input is a DBA file (or a folder containing DBAs). Matching original CGF CHR USDA skeletons must already exist in the corresponding Output folder. Click Export Animation Only. Clean native animations and existing-rig Max loaders are written under NATIVE_ANIMATION. No axis markers or HTR pivot adjustment are added. Supplied Hornet front/left clips are validated; other rigs/formats may be rejected or skipped.\nFor a normal geometry batch leave Processor at <None>; export decoded animation separately afterward.\n\nOTHER BUTTONS\nFile: choose one input asset. Open Output: open the selected destination.\nCollect Existing Outputs: collect already-generated exports without converting.\nCreate Desktop Shortcut: point the desktop shortcut to this installed application folder.\n\nDIAGNOSTICS\nHidden by default. Show diagnostics reveals experimental processors, diagnostic presets, reference paths, extra arguments, dry run, command preview and detailed listener. Logs are still written when diagnostics are hidden. Turning diagnostics off clears extra arguments and format overrides and disables dry run. Diagnostic selections are replaced with production-safe choices.\n\nVERSION / LAUNCHING\nThe title must show 0.3.11 and Input Folder must appear beside File.\nIf it shows 0.3.6, close the old window and launch START_SC_CGF_Converter.vbs directly from the newly extracted folder. Then use Create Desktop Shortcut to update the old shortcut.'

class HoverHelp:
    def __init__(self, widget, text):
        self.widget=widget; self.text=text; self.timer=None; self.popup=None
        widget.bind("<Enter>",self.schedule,add="+")
        widget.bind("<Leave>",self.hide,add="+")
        widget.bind("<ButtonPress>",self.hide,add="+")
        widget.bind("<Destroy>",self.hide,add="+")
    def schedule(self,event=None):
        self.hide(); self.timer=self.widget.after(500,self.show)
    def show(self):
        self.timer=None
        if not self.widget.winfo_exists():return
        self.popup=tk.Toplevel(self.widget);self.popup.wm_overrideredirect(True)
        self.popup.geometry(f"+{self.widget.winfo_rootx()+12}+{self.widget.winfo_rooty()+self.widget.winfo_height()+5}")
        ttk.Label(self.popup,text=self.text,wraplength=420,padding=8,relief="solid").pack()
    def hide(self,event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer);self.timer=None
        if self.popup is not None:
            self.popup.destroy();self.popup=None

ASSET_EXTENSIONS = {".cgf", ".cga", ".chr", ".skin", ".anim", ".dba"}

def plan_batch_jobs(input_path, output_path, recursive=True, preserve=True, dba_only=False, geometry_only=False, extensions=None):
    source=Path(input_path).resolve(); output=Path(output_path).resolve()
    if not source.exists(): raise ValueError("Input does not exist.")
    allowed={".dba"} if dba_only else (set(extensions) if extensions is not None else ({".cgf", ".cga", ".chr", ".skin"} if geometry_only else ASSET_EXTENSIONS))
    if not source.is_dir():
        if source.suffix.lower() not in allowed: raise ValueError("Unsupported input asset type.")
        return [(source,output)]
    if output==source or source.is_relative_to(output):
        raise ValueError("Output must not equal the input folder or contain the input folder.")
    assets=[];pending=[source]
    while pending:
        folder=pending.pop()
        for entry in sorted(folder.iterdir()):
            if entry.is_symlink() or entry==output or entry.is_relative_to(output):continue
            if entry.is_dir():
                if recursive:pending.append(entry)
            elif entry.is_file() and entry.suffix.lower() in allowed:assets.append(entry)
    if not assets:raise ValueError("No supported input assets found.")
    jobs=[];names={}
    for asset in sorted(assets):
        destination=output/asset.parent.relative_to(source) if preserve else output
        key=(str(destination).casefold(),asset.stem.casefold())
        if key in names and names[key].parent!=asset.parent:
            raise ValueError("Flat output name collision: "+asset.stem+". Enable Preserve input folder structure.")
        names[key]=asset;jobs.append((asset,destination))
    return jobs

@dataclass
class Processor:
    path: Path
    module: Any
    meta: dict

    @property
    def id(self) -> str:
        return str(self.meta.get("id", self.path.stem))

    @property
    def display(self) -> str:
        status = str(self.meta.get("status", "unknown")).upper()
        version = str(self.meta.get("version", "?"))
        name = str(self.meta.get("name", self.id))
        return f"[{status}] {name}  v{version}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x540")
        self.minsize(1040, 480)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._icon_photo = None
        try:
            if os.name == "nt" and APP_ICON_ICO.exists():
                self.iconbitmap(default=str(APP_ICON_ICO))
            elif APP_ICON_PNG.exists():
                self._icon_photo = tk.PhotoImage(file=str(APP_ICON_PNG))
                self.iconphoto(True, self._icon_photo)
        except Exception:
            pass

        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)

        self.settings = self.load_settings()
        self.profiles: dict[str, dict] = {}
        self.presets: dict[str, dict] = {}
        self.processors: dict[str, Processor] = {}
        self.processor_display_to_id: dict[str, str] = {}
        self.ui_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_report = ""
        self.last_command: list[str] = []
        self.converter_usage_text = ""
        self.converter_caps: set[str] = set()
        self.converter_caps_known = False

        self.make_vars()
        self.build_ui()
        self.reload_everything(initial=True)
        self.restore_settings()
        self.after(75, self.pump_ui_queue)

    def make_vars(self):
        self.var_converter = tk.StringVar()
        self.var_converter_info = tk.StringVar(value="Not probed")
        self.var_profile = tk.StringVar()
        self.var_preset = tk.StringVar()
        self.var_processor = tk.StringVar(value="<None>")
        self.var_input = tk.StringVar()
        self.var_objectdir = tk.StringVar()
        self.var_output = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.var_reference = tk.StringVar()
        self.var_format = tk.StringVar(value="Preset")
        self.var_extra = tk.StringVar()
        self.var_dryrun = tk.BooleanVar(value=False)
        self.var_collect_outputs = tk.BooleanVar(value=True)
        self.var_batch = tk.BooleanVar(value=True)
        self.var_preserve_folders = tk.BooleanVar(value=True)
        self.var_diagnostics = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Ready")
        self.var_progress = tk.DoubleVar(value=0.0)

    def button(self,parent,text,command,help_text):
        w=ttk.Button(parent,text=text,command=command)
        HoverHelp(w,help_text)
        return w

    def build_ui(self):
        outer=ttk.Frame(self,padding=10);outer.pack(fill="both",expand=True)
        outer.columnconfigure(0,weight=1);outer.rowconfigure(5,weight=1)
        self.outer=outer;self.advanced_widgets=[]
        header=ttk.Frame(outer);header.grid(row=0,column=0,sticky="ew")
        ttk.Label(header,text="SC CGF Converter 0.3.11 — Batch Export",font=("Segoe UI",13,"bold")).pack(side="left")
        self.button(header,"Help",self.show_help,"Open setup, normal batch export and animation instructions.").pack(side="right")
        toggle=ttk.Checkbutton(header,text="Show diagnostics",variable=self.var_diagnostics,command=self.toggle_diagnostics)
        toggle.pack(side="right",padx=12);HoverHelp(toggle,"Show command preview, detailed log and experimental presets/processors. Hidden by default.")
        f=ttk.LabelFrame(outer,text="Converter",padding=8);f.grid(row=1,column=0,sticky="ew",pady=(8,0));f.columnconfigure(1,weight=1)
        ttk.Label(f,text="cgf-converter.exe").grid(row=0,column=0,sticky="w")
        ttk.Entry(f,textvariable=self.var_converter).grid(row=0,column=1,sticky="ew",padx=6)
        self.button(f,"Browse",self.pick_converter,"Select your stock cgf-converter.exe.").grid(row=0,column=2)
        self.button(f,"Check Converter",self.probe_converter,"Read the converter's supported switches and output-folder capability. Run once after choosing a different converter.").grid(row=0,column=3,padx=6)
        ttk.Label(f,textvariable=self.var_converter_info).grid(row=1,column=1,columnspan=3,sticky="w",pady=(4,0))
        f2=ttk.LabelFrame(outer,text="Export Settings",padding=8);f2.grid(row=2,column=0,sticky="ew",pady=(8,0))
        for c in (1,3,5):f2.columnconfigure(c,weight=1)
        ttk.Label(f2,text="Game").grid(row=0,column=0)
        self.cb_profile=ttk.Combobox(f2,textvariable=self.var_profile,state="readonly",width=18);self.cb_profile.grid(row=0,column=1,sticky="ew",padx=5)
        self.cb_profile.bind("<<ComboboxSelected>>",lambda e:self.profile_changed())
        ttk.Label(f2,text="Preset").grid(row=0,column=2)
        self.cb_preset=ttk.Combobox(f2,textvariable=self.var_preset,state="readonly",width=36);self.cb_preset.grid(row=0,column=3,sticky="ew",padx=5)
        HoverHelp(self.cb_preset,"SC_Normal_Batch_USDA is the normal batch preset. CHR/CGA include animation; SKIN/CGF export geometry. SC_Static_USDA omits animation. Other named presets filter batches by their listed file types.")
        self.cb_preset.bind("<<ComboboxSelected>>",lambda e:self.preview_command(silent=True))
        ttk.Label(f2,text="Processor").grid(row=0,column=4)
        self.cb_processor=ttk.Combobox(f2,textvariable=self.var_processor,state="readonly",width=30);self.cb_processor.grid(row=0,column=5,sticky="ew",padx=5)
        HoverHelp(self.cb_processor,"Use <None> for normal exporting. SC Native Animation Export is the separate decoded DBA animation workflow; it requires matching exported CHR skeletons.")
        self.reload_button=self.button(f2,"Reload Modules",self.reload_everything,"Reload processor files after installing or editing one.");self.reload_button.grid(row=1,column=5,sticky="e",pady=5)
        self.advanced_widgets.append(self.reload_button)
        f3=ttk.LabelFrame(outer,text="Files and Folders",padding=8);f3.grid(row=3,column=0,sticky="ew",pady=(8,0));f3.columnconfigure(1,weight=1)
        self.path_row(f3,0,"Input file / folder",self.var_input,self.pick_input,"File","Choose one source asset for a single-file export.")
        self.button(f3,"Input Folder",self.pick_input_folder,"Choose the input root. Batch processing scans this folder and its subfolders.").grid(row=0,column=3,padx=(5,0))
        self.path_row(f3,1,"Game/Data root",self.var_objectdir,self.pick_objectdir,"Folder","Choose the extracted Data folder that contains Objects and Animations, for resolving materials and animation references.")
        self.path_row(f3,2,"Output folder",self.var_output,self.pick_output,"Folder","Choose the export destination. Source subfolders are reproduced underneath this folder.")
        self.reference_row=ttk.Frame(f3);self.reference_row.grid(row=3,column=0,columnspan=4,sticky="ew");self.reference_row.columnconfigure(1,weight=1)
        self.path_row(self.reference_row,0,"Reference folder",self.var_reference,self.pick_reference,"Folder","Optional reference data for animation processors. Not needed for normal batch exporting.");self.advanced_widgets.append(self.reference_row)
        opts=ttk.Frame(f3);opts.grid(row=4,column=0,columnspan=4,sticky="ew",pady=6)
        for text,var,helptext in [
            ("Batch folder processing (recursive)",self.var_batch,"On: process assets in all input subfolders. Off: process only files directly in the chosen input folder. A file input always processes one file."),
            ("Preserve input folder structure",self.var_preserve_folders,"On: Input/Ships/Anvil exports to Output/Ships/Anvil. Off: output is flat; conflicting names are rejected."),
            ("Collect native outputs",self.var_collect_outputs,"Keep enabled. If the converter writes beside the source, copy its generated exports to the chosen output folder.")]:
            w=ttk.Checkbutton(opts,text=text,variable=var);w.pack(side="left",padx=(0,14));HoverHelp(w,helptext)
        advanced=ttk.Frame(f3);advanced.grid(row=5,column=0,columnspan=4,sticky="ew");advanced.columnconfigure(3,weight=1)
        ttk.Label(advanced,text="Format override").grid(row=0,column=0)
        ttk.Combobox(advanced,textvariable=self.var_format,values=list(OUTPUT_FLAGS),state="readonly",width=10).grid(row=0,column=1,padx=6)
        ttk.Label(advanced,text="Extra args").grid(row=0,column=2)
        ttk.Entry(advanced,textvariable=self.var_extra).grid(row=0,column=3,sticky="ew",padx=6)
        w=ttk.Checkbutton(advanced,text="Dry run",variable=self.var_dryrun);w.grid(row=0,column=4);HoverHelp(w,"List planned per-file commands without converting assets or running processors.")
        self.advanced_widgets.append(advanced)
        actions=ttk.Frame(outer);actions.grid(row=4,column=0,sticky="ew",pady=(8,0))
        self.btn_convert=self.button(actions,"EXPORT",self.start_convert,"Export the chosen file or batch folder using the selected preset and output structure.");self.btn_convert.pack(side="left")
        self.btn_processor=self.button(actions,"Export Animation Only",self.start_processor_only,"Run the selected processor without stock conversion. Select SC Native Animation Export for decoded DBA clips; matching source CHR USDA skeletons must already exist in Output.");self.btn_processor.pack(side="left",padx=6)
        self.button(actions,"Open Output",self.open_output,"Open the chosen output folder in Explorer.").pack(side="left")
        self.button(actions,"Collect Existing Outputs",self.collect_existing_outputs_now,"Copy matching exports already beside the selected input assets into the chosen output structure. Does not convert.").pack(side="left",padx=6)
        self.button(actions,"Create Desktop Shortcut",self.create_desktop_shortcut,"Create or replace the desktop shortcut so it launches this 0.3.11 application folder.").pack(side="left")
        self.build_button=self.button(actions,"Build Command",self.preview_command,"Preview the stock converter command without executing it.");self.build_button.pack(side="left",padx=6)
        self.advanced_widgets.append(self.build_button)
        center=ttk.Frame(outer);center.grid(row=5,column=0,sticky="nsew",pady=(8,0));center.columnconfigure(0,weight=1);center.rowconfigure(1,weight=1)
        self.summary=ttk.Label(center,text="Normal batch: StarCitizen  |  SC_Normal_Batch_USDA  |  Processor <None>\nChoose Input Folder, Game/Data root and Output folder, then EXPORT.\nBoth batch options are enabled by default. Keep Collect native outputs enabled.",padding=8,wraplength=1020)
        self.summary.grid(row=0,column=0,sticky="nw")
        fc=ttk.LabelFrame(center,text="Command Preview",padding=6);fc.grid(row=0,column=0,sticky="ew");fc.columnconfigure(0,weight=1)
        self.txt_command=tk.Text(fc,height=3,wrap="word",font=("Consolas",9));self.txt_command.grid(row=0,column=0,sticky="ew");self.advanced_widgets.append(fc)
        fl=ttk.LabelFrame(center,text="Diagnostic / Listener",padding=6);fl.grid(row=1,column=0,sticky="nsew");fl.rowconfigure(0,weight=1);fl.columnconfigure(0,weight=1)
        self.txt_log=tk.Text(fl,wrap="none",font=("Consolas",9));self.txt_log.grid(row=0,column=0,sticky="nsew")
        y=ttk.Scrollbar(fl,orient="vertical",command=self.txt_log.yview);y.grid(row=0,column=1,sticky="ns")
        x=ttk.Scrollbar(fl,orient="horizontal",command=self.txt_log.xview);x.grid(row=1,column=0,sticky="ew");self.txt_log.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        tools=ttk.Frame(fl);tools.grid(row=2,column=0,sticky="e")
        self.button(tools,"Clear",self.clear_log,"Clear the displayed listener text.").pack(side="left")
        self.button(tools,"Copy Report",self.copy_report,"Copy the current processor report or listener text for troubleshooting.").pack(side="left",padx=5)
        self.advanced_widgets.append(fl)
        status=ttk.Frame(outer);status.grid(row=6,column=0,sticky="ew",pady=(7,0));status.columnconfigure(0,weight=1)
        ttk.Label(status,textvariable=self.var_status).grid(row=0,column=0,sticky="w")
        ttk.Progressbar(status,variable=self.var_progress,maximum=100,length=230).grid(row=0,column=1,sticky="e")
        self.toggle_diagnostics(refresh=False)

    def path_row(self,parent,row,label,var,command,button_text,help_text="Choose a path."):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky="w",pady=2)
        w=ttk.Entry(parent,textvariable=var);w.grid(row=row,column=1,sticky="ew",padx=6,pady=2);HoverHelp(w,help_text)
        self.button(parent,button_text,command,help_text).grid(row=row,column=2,pady=2)

    def toggle_diagnostics(self,refresh=True):
        visible=self.var_diagnostics.get()
        for w in self.advanced_widgets:
            if w is self.build_button:
                if visible:w.pack(side="left",padx=6)
                else:w.pack_forget()
            elif visible:w.grid()
            else:w.grid_remove()
        if visible:self.summary.grid_remove()
        else:
            self.summary.grid()
            self.var_extra.set("");self.var_dryrun.set(False);self.var_format.set("Preset")
        self.geometry("1180x840" if visible else "1180x540")
        if refresh:self.profile_changed()

    def show_help(self):
        win=tk.Toplevel(self);win.title("SC CGF Converter — Help");win.geometry("800x650");win.transient(self)
        text=tk.Text(win,wrap="word",padx=14,pady=14,font=("Segoe UI",10));text.pack(fill="both",expand=True)
        text.insert("1.0",HELP_TEXT+"\n\nRunning application folder:\n"+str(ROOT))
        text.configure(state="disabled")
        self.button(win,"Close",win.destroy,"Close Help and return to the exporter.").pack(pady=8)

    # ---------- settings / discovery ----------
    def load_settings(self):
        try:
            return read_json(SETTINGS_FILE)
        except Exception:
            return {}

    def restore_settings(self):
        s = self.settings
        self.var_converter.set(s.get("converter", self.find_converter_default()))
        self.var_input.set(s.get("input", ""))
        self.var_objectdir.set(s.get("objectdir", ""))
        self.var_output.set(s.get("output", str(DEFAULT_OUTPUT)))
        self.var_reference.set(s.get("reference", ""))
        self.var_extra.set(s.get("extra", ""))
        self.var_format.set(s.get("format", "Preset"))
        self.var_collect_outputs.set(bool(s.get("collect_outputs", True)))
        self.var_batch.set(bool(s.get("batch_folders", True)))
        self.var_preserve_folders.set(bool(s.get("preserve_folders", True)))
        if s.get("profile") in self.profiles:
            self.var_profile.set(s["profile"])
        elif "StarCitizen" in self.profiles:
            self.var_profile.set("StarCitizen")
        elif self.profiles:
            self.var_profile.set(next(iter(self.profiles)))
        self.profile_changed(preferred_preset=s.get("preset"))
        preferred_processor = s.get("processor_id")
        if preferred_processor and preferred_processor in self.processors and self.processor_compatible(self.processors[preferred_processor]):
            self.var_processor.set(self.processors[preferred_processor].display)
        if not self.var_diagnostics.get():
            self.var_extra.set("");self.var_format.set("Preset");self.var_dryrun.set(False)
        self.preview_command(silent=True)

    def save_settings(self):
        proc_id = self.selected_processor_id()
        data = {
            "converter": self.var_converter.get(),
            "profile": self.var_profile.get(),
            "preset": self.selected_preset_id(),
            "processor_id": proc_id,
            "input": self.var_input.get(),
            "objectdir": self.var_objectdir.get(),
            "output": self.var_output.get(),
            "reference": self.var_reference.get(),
            "format": self.var_format.get(),
            "extra": self.var_extra.get(),
            "collect_outputs": bool(self.var_collect_outputs.get()),
            "batch_folders": bool(self.var_batch.get()),
            "preserve_folders": bool(self.var_preserve_folders.get()),
        }
        write_json(SETTINGS_FILE,data)

    def find_converter_default(self):
        local = ROOT / "cgf-converter.exe"
        if local.exists(): return str(local)
        found = shutil.which("cgf-converter") or shutil.which("cgf-converter.exe")
        return found or ""

    def reload_everything(self, initial=False):
        old_profile = self.var_profile.get()
        old_preset = self.var_preset.get()
        old_proc = self.selected_processor_id()
        self.profiles.clear(); self.presets.clear(); self.processors.clear(); self.processor_display_to_id.clear()
        for p in sorted(PROFILE_DIR.glob("*.json")):
            try:
                d=read_json(p); key=d.get("id",p.stem); d["_path"]=str(p); self.profiles[key]=d
            except Exception as e:
                self.log(f"PROFILE ERROR {p.name}: {e}")
        for p in sorted(PRESET_DIR.rglob("*.json")):
            try:
                d=read_json(p); key=d.get("id",p.stem); d["_path"]=str(p); self.presets[key]=d
            except Exception as e:
                self.log(f"PRESET ERROR {p.name}: {e}")
        for folder in MODULE_DIRS:
            for p in sorted(folder.glob("*.py")):
                if p.name.startswith("_"): continue
                try:
                    unique=f"sc_cgf_ext_{p.stem}_{time.time_ns()}"
                    spec=importlib.util.spec_from_file_location(unique,p)
                    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
                    meta=getattr(mod,"PROCESSOR_META",{})
                    if not callable(getattr(mod,"run",None)):
                        raise RuntimeError("module has no run(context) function")
                    proc=Processor(p,mod,meta); self.processors[proc.id]=proc
                    self.processor_display_to_id[proc.display]=proc.id
                except Exception as e:
                    self.log(f"MODULE ERROR {p.name}: {e}")
        self.cb_profile["values"] = list(self.profiles.keys())
        if old_profile in self.profiles: self.var_profile.set(old_profile)
        elif self.profiles and not self.var_profile.get(): self.var_profile.set(next(iter(self.profiles)))
        self.profile_changed(preferred_preset=old_preset)
        proc_values=["<None>"]+[p.display for p in self.processors.values() if self.processor_compatible(p)]
        self.cb_processor["values"] = proc_values
        if old_proc and old_proc in self.processors and self.processors[old_proc].display in proc_values:
            self.var_processor.set(self.processors[old_proc].display)
        elif self.var_processor.get() not in proc_values:
            self.var_processor.set("<None>")
        if not initial:
            self.log(f"Reload complete | profiles={len(self.profiles)} | presets={len(self.presets)} | processors={len(self.processors)}")

    def preset_label(self,pid):
        return self.presets[pid].get("display_name",pid)

    def selected_preset_id(self):
        selected=self.var_preset.get()
        if selected in self.presets:return selected
        return next((pid for pid in self.presets if self.preset_label(pid)==selected),selected)

    def profile_changed(self, preferred_preset=None):
        profile_id=self.var_profile.get();ids=[]
        for pid,p in self.presets.items():
            targets=p.get("profiles",["*"])
            if ("*" in targets or profile_id in targets) and (self.var_diagnostics.get() or not any(x in pid.lower() for x in ("diagnostic","raw_"))):ids.append(pid)
        self.cb_preset["values"]=[self.preset_label(pid) for pid in ids]
        preferred=preferred_preset if preferred_preset in self.presets else next((pid for pid in self.presets if self.preset_label(pid)==preferred_preset),None)
        current=self.selected_preset_id()
        chosen=preferred if preferred in ids else (current if current in ids else ("SC_Normal_Batch_USDA" if "SC_Normal_Batch_USDA" in ids else (ids[0] if ids else None)))
        self.var_preset.set(self.preset_label(chosen) if chosen else "")
        proc_values=["<None>"]+[p.display for p in self.processors.values() if self.processor_compatible(p)]
        self.cb_processor["values"]=proc_values
        if self.var_processor.get() not in proc_values:self.var_processor.set("<None>")
        self.preview_command(silent=True)

    def processor_compatible(self, proc: Processor):
        targets=proc.meta.get("profiles",["*"])
        return ("*" in targets or self.var_profile.get() in targets) and (self.var_diagnostics.get() or proc.id=="sc_native_animation_export")

    def selected_processor_id(self):
        return self.processor_display_to_id.get(self.var_processor.get())

    def selected_processor(self):
        pid=self.selected_processor_id(); return self.processors.get(pid) if pid else None

    # ---------- picker helpers ----------
    def pick_converter(self):
        p=filedialog.askopenfilename(title="Select stock cgf-converter.exe",filetypes=[("Executable","*.exe"),("All files","*.*")])
        if p: self.var_converter.set(p); self.preview_command(silent=True)
    def pick_input(self):
        p=filedialog.askopenfilename(title="Select CryEngine asset",filetypes=[("CryEngine assets","*.cgf *.cga *.chr *.skin *.anim *.dba"),("All files","*.*")])
        if p: self.var_input.set(p); self.preview_command(silent=True)
    def pick_input_folder(self):
        p=filedialog.askdirectory(title="Select input folder for recursive batch processing")
        if p: self.var_input.set(p); self.preview_command(silent=True)

    def pick_objectdir(self):
        p=filedialog.askdirectory(title="Select extracted game/Object root")
        if p: self.var_objectdir.set(p); self.preview_command(silent=True)
    def pick_output(self):
        p=filedialog.askdirectory(title="Select output folder")
        if p: self.var_output.set(p); self.preview_command(silent=True)
    def pick_reference(self):
        p=filedialog.askdirectory(title="Select reference/test-data folder")
        if p: self.var_reference.set(p)

    # ---------- converter capabilities ----------
    def parse_converter_usage(self, text: str) -> set[str]:
        low = (text or "").lower()
        caps: set[str] = set()
        # Only trust switches actually advertised by the selected executable.
        if "-outdir" in low or "-out " in low or "\n-out:" in low:
            caps.add("outdir")
        if "-anim" in low or "-animations" in low:
            caps.add("anim")
        if "-objectdir" in low:
            caps.add("objectdir")
        if "-usda" in low or "-usd" in low:
            caps.add("usd")
        if "-dae" in low:
            caps.add("dae")
        if "-gltf" in low:
            caps.add("gltf")
        if "-glb" in low:
            caps.add("glb")
        return caps

    def native_output_dir_supported(self) -> bool:
        return self.converter_caps_known and "outdir" in self.converter_caps

    # ---------- command ----------
    def current_profile(self): return self.profiles.get(self.var_profile.get(),{})
    def current_preset(self): return self.presets.get(self.selected_preset_id(),{})

    def build_command(self, input_path=None, output_path=None):
        exe=self.var_converter.get().strip() or "cgf-converter"
        inp=self.var_input.get().strip() if input_path is None else str(input_path)
        cmd=[exe]
        if inp: cmd.append(inp)
        args=list(self.current_preset().get("converter_args",[]))
        if self.current_preset().get("per_asset_animation"):
            args=[a for a in args if str(a).lower()!="-anim"]
            if Path(inp).suffix.lower() in {".chr", ".cga"}:args.append("-anim")
        override=OUTPUT_FLAGS.get(self.var_format.get())
        if override:
            args=[a for a in args if str(a).lower() not in OUTPUT_FLAG_SET]
            args.insert(0,override)
        obj=self.var_objectdir.get().strip()
        out=self.var_output.get().strip() if output_path is None else str(output_path)
        if obj and "-objectdir" not in [str(a).lower() for a in args]: args += ["-objectdir",obj]
        # Output-directory support varies between builds. Never guess: only use
        # -out when the selected executable explicitly advertised it during Probe.
        if out and self.native_output_dir_supported() and "-out" not in [str(a).lower() for a in args] and "-outdir" not in [str(a).lower() for a in args]:
            args += ["-outdir" if "-outdir" in self.converter_usage_text.lower() else "-out", out]
        extra=self.var_extra.get().strip()
        if extra:
            try: args += shlex.split(extra,posix=False)
            except Exception: args += extra.split()
        cmd += [str(a) for a in args]
        return cmd

    def preview_command(self, silent=False):
        cmd=self.build_command(); self.last_command=cmd
        self.txt_command.delete("1.0","end"); self.txt_command.insert("1.0",win_cmdline(cmd))
        if not silent: self.log("COMMAND PREVIEW\n"+win_cmdline(cmd))
        return cmd

    def probe_converter(self):
        exe=self.var_converter.get().strip() or self.find_converter_default()
        if not exe:
            messagebox.showwarning(APP_TITLE,"Select cgf-converter.exe first."); return
        def work():
            self.post_status("Probing converter...",15)
            try:
                cp=subprocess.run([exe,"-usage"],capture_output=True,text=True,errors="replace",timeout=20,**hidden_process_kwargs())
                out=(cp.stdout or "")+(cp.stderr or "")
                self.converter_usage_text = out
                self.converter_caps = self.parse_converter_usage(out)
                self.converter_caps_known = True
                version_line = next((x.strip() for x in out.splitlines() if "converter v" in x.lower()), "CryEngine Converter")
                native_out = "YES" if "outdir" in self.converter_caps else "NO"
                self.ui_queue.put(("converter_info", f"{version_line} | Native output folder: {native_out}"))
                self.post_log("CONVERTER PROBE\n"+out.strip())
                if "outdir" not in self.converter_caps:
                    self.post_log("SC CC CAPABILITY: This executable does not advertise -out/-outdir. It writes beside the source; SC CC will collect newly created/updated export files into the selected Output folder after conversion.")
                self.ui_queue.put(("refresh_preview", None))
            except Exception as e:
                self.ui_queue.put(("converter_info",f"Probe failed: {e}")); self.post_log(f"CONVERTER PROBE FAILED: {e}")
            self.post_status("Ready",0)
        self.start_worker(work)

    # ---------- execution ----------
    def make_context(self, command=None):
        return {
            "app_version": APP_VERSION,
            "root": str(ROOT),
            "profile_id": self.var_profile.get(),
            "profile": self.current_profile(),
            "preset_id": self.selected_preset_id(),
            "preset": self.current_preset(),
            "converter": self.var_converter.get().strip(),
            "input": self.var_input.get().strip(),
            "objectdir": self.var_objectdir.get().strip(),
            "output": self.var_output.get().strip(),
            "reference": self.var_reference.get().strip(),
            "format_override": self.var_format.get(),
            "command": command or self.build_command(),
            "converter_cwd": self.converter_working_directory(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "collect_outputs": bool(self.var_collect_outputs.get()),
            "batch_folders": bool(self.var_batch.get()),
            "preserve_folders": bool(self.var_preserve_folders.get()),
        }

    def converter_working_directory(self) -> str | None:
        """Pick a stable working directory for the stock converter.

        Star Citizen material/texture references can be relative to the extracted
        game-data root even when -objectdir is supplied. Prefer the selected
        Game/Object Root so those relative lookups do not fall back to the SC CC
        program directory. If unavailable, fall back to the input asset folder.
        """
        obj=self.var_objectdir.get().strip()
        if obj:
            try:
                op=Path(obj)
                if op.is_dir():
                    return str(op)
            except Exception:
                pass
        inp=self.var_input.get().strip()
        if inp:
            try:
                ip=Path(inp)
                if ip.exists():
                    return str(ip.parent)
            except Exception:
                pass
        return None

    def expected_export_extensions(self, command: list[str]) -> set[str]:
        """Return likely primary export extensions for the selected converter command."""
        low={str(x).lower() for x in command}
        if "-dae" in low:
            return {".dae"}
        if "-glb" in low:
            return {".glb"}
        if "-gltf" in low:
            return {".gltf", ".bin"}
        if "-obj" in low:
            return {".obj", ".mtl"}
        # -usd and -usda builds generally emit ASCII .usda in the version under test.
        return {".usda", ".usd"}

    def snapshot_native_exports(self, input_path: str, command: list[str]) -> dict[str, tuple[int,int]]:
        """Snapshot converter-owned outputs next to the input before running stock converter.

        The selected Cryengine-Converter v2.0.0 cannot choose an output directory. It
        emits the primary model and animation files beside the source. Restrict the
        snapshot to files whose names are derived from the input stem so unrelated
        game files can never be collected accidentally.
        """
        try:
            ip=Path(input_path)
            parent=ip.parent
            prefix=ip.stem.lower()
            exts=self.expected_export_extensions(command)
            out={}
            for f in parent.iterdir():
                try:
                    if not f.is_file() or f.suffix.lower() not in exts:
                        continue
                    if not f.stem.lower().startswith(prefix):
                        continue
                    st=f.stat(); out[str(f.resolve())]=(st.st_mtime_ns,st.st_size)
                except Exception:
                    pass
            return out
        except Exception:
            return {}

    def collect_native_exports(self, input_path: str, command: list[str], before: dict[str, tuple[int,int]], output_path=None) -> list[str]:
        """Copy newly-created/updated stock-converter exports into SC CC Output."""
        if not self.var_collect_outputs.get():
            self.post_log("OUTPUT COLLECTION: disabled")
            return []
        out_text=self.var_output.get().strip() if output_path is None else str(output_path)
        if not out_text:
            self.post_log("OUTPUT COLLECTION: no Output folder selected")
            return []
        try:
            ip=Path(input_path)
            parent=ip.parent
            prefix=ip.stem.lower()
            exts=self.expected_export_extensions(command)
            outdir=Path(out_text)
            outdir.mkdir(parents=True,exist_ok=True)
            collected=[]
            for f in sorted(parent.iterdir()):
                try:
                    if not f.is_file() or f.suffix.lower() not in exts:
                        continue
                    if not f.stem.lower().startswith(prefix):
                        continue
                    st=f.stat(); key=str(f.resolve()); now=(st.st_mtime_ns,st.st_size)
                    if before.get(key)==now:
                        continue
                    dest=outdir/f.name
                    try:
                        if f.resolve()==dest.resolve():
                            collected.append(str(dest)); continue
                    except Exception:
                        pass
                    shutil.copy2(f,dest)
                    collected.append(str(dest))
                    self.post_log(f"COLLECTED OUTPUT: {f.name} -> {dest}")
                except Exception as exc:
                    self.post_log(f"OUTPUT COLLECTION WARNING: {f} | {exc}")
            if collected:
                self.post_log(f"OUTPUT COLLECTION COMPLETE: {len(collected)} file(s) copied to {outdir}")
            else:
                self.post_log("OUTPUT COLLECTION: no new/updated primary export files detected beside the source")
            return collected
        except Exception:
            self.post_log("OUTPUT COLLECTION FAILED\n"+traceback.format_exc())
            return []

    def planned_jobs(self, processor_only=False):
        inp=Path(self.var_input.get().strip()).expanduser().resolve()
        if not self.var_input.get().strip() or not inp.exists():
            raise ValueError("Select an existing input file or folder.")
        if not self.var_output.get().strip():
            raise ValueError("Select an Output folder.")
        return plan_batch_jobs(inp, Path(self.var_output.get()).expanduser().resolve(),
                               bool(self.var_batch.get()), bool(self.var_preserve_folders.get()),
                               processor_only and self.selected_processor_id()=="sc_native_animation_export",
                               not processor_only and bool(self.current_preset().get("per_asset_animation")),
                               self.current_preset().get("input_extensions") if not processor_only else None)

    def start_convert(self):
        if self.worker and self.worker.is_alive(): return
        try:
            jobs=self.planned_jobs()
            commands=[self.build_command(ip,op) for ip,op in jobs]
        except Exception as exc:
            messagebox.showwarning(APP_TITLE,str(exc)); return
        dry=bool(self.var_dryrun.get())
        if not dry and not (Path(commands[0][0]).exists() or shutil.which(commands[0][0])):
            messagebox.showwarning(APP_TITLE,"cgf-converter executable was not found. Select the stock converter first."); return
        native=self.native_output_dir_supported()
        if not native and not dry and not self.var_collect_outputs.get():
            messagebox.showwarning(APP_TITLE,"Enable Collect native outputs to export into the selected Output folder with this converter."); return
        self.save_settings()
        procmod=self.selected_processor()
        template=self.make_context(commands[0])
        converter_cwd=self.converter_working_directory()
        def work():
            failures=0
            self.post_log(f"BATCH START: {len(jobs)} asset(s)")
            for index,((ip,op),cmd) in enumerate(zip(jobs,commands),1):
                self.post_status(f"Converting {index}/{len(jobs)}: {ip.name}",100*(index-1)/len(jobs))
                self.post_log(f"INPUT: {ip}\nOUTPUT: {op}\n"+win_cmdline(cmd))
                try:
                    if dry:
                        self.post_log("DRY RUN: converter and processor were not executed."); continue
                    op.mkdir(parents=True,exist_ok=True)
                    before=self.snapshot_native_exports(str(ip),cmd) if not native else {}
                    proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors="replace",bufsize=1,cwd=converter_cwd,**hidden_process_kwargs())
                    assert proc.stdout is not None
                    for line in proc.stdout: self.post_log(line.rstrip())
                    rc=proc.wait()
                    self.post_log(f"CONVERTER EXIT: {rc}")
                    if rc!=0: raise RuntimeError(f"Converter returned {rc}")
                    collected=self.collect_native_exports(str(ip),cmd,before,op) if not native else []
                    if procmod:
                        context=dict(template,input=str(ip),output=str(op),command=cmd,collected_outputs=collected)
                        if not self.run_processor(procmod,context):raise RuntimeError("Selected processor failed; see the log.")
                except Exception:
                    failures+=1;self.post_log("ASSET FAILED\n"+traceback.format_exc())
            self.post_log(f"BATCH COMPLETE: {len(jobs)} asset(s), {failures} conversion failure(s)")
            self.post_status("Dry run complete" if dry else ("Done" if not failures else f"Done with {failures} failure(s)"),100)
            self.write_session_log()
        self.start_worker(work)

    def collect_existing_outputs_now(self):
        if self.worker and self.worker.is_alive(): return
        try:
            jobs=self.planned_jobs()
            commands=[self.build_command(ip,op) for ip,op in jobs]
        except Exception as exc:
            messagebox.showwarning(APP_TITLE,str(exc)); return
        self.save_settings()
        def work():
            count=0
            for index,((ip,op),cmd) in enumerate(zip(jobs,commands),1):
                self.post_status(f"Collecting {index}/{len(jobs)}: {ip.name}",100*(index-1)/len(jobs))
                count+=len(self.collect_native_exports(str(ip),cmd,{},op))
            self.post_log(f"COLLECT EXISTING COMPLETE: {count} file(s)")
            self.post_status(f"Collected {count} existing outputs",100)
            self.write_session_log()
        self.start_worker(work)

    def start_processor_only(self):
        if self.worker and self.worker.is_alive(): return
        procmod=self.selected_processor()
        if not procmod:
            messagebox.showwarning(APP_TITLE,"Select a processor module first."); return
        try: jobs=self.planned_jobs(processor_only=True)
        except Exception as exc:
            messagebox.showwarning(APP_TITLE,str(exc)); return
        self.save_settings()
        template=self.make_context()
        def work():
            failures=0
            for index,(ip,op) in enumerate(jobs,1):
                self.post_status(f"Processing {index}/{len(jobs)}: {ip.name}",100*(index-1)/len(jobs))
                op.mkdir(parents=True,exist_ok=True)
                if not self.run_processor(procmod,dict(template,input=str(ip),output=str(op))):failures+=1
            self.post_status("Processor batch complete" if not failures else f"Processor batch: {failures} failure(s)",100)
            self.write_session_log()
        self.start_worker(work)

    def run_processor(self, procmod: Processor, context: dict):
        self.post_log("-"*76+f"\nPROCESSOR START: {procmod.display}\nFILE: {procmod.path}")
        try:
            context=dict(context)
            context["processor_meta"]=procmod.meta
            result=procmod.module.run(context)
            if isinstance(result,dict):
                self.post_log(json.dumps(result,indent=2,default=str))
            elif result is not None:
                self.post_log(str(result))
            self.post_log("PROCESSOR COMPLETE")
            return True
        except Exception:
            self.post_log("PROCESSOR FAILED\n"+traceback.format_exc())
            return False

    def start_worker(self, target: Callable):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE,"A job is already running."); return
        self.btn_convert.state(["disabled"]); self.btn_processor.state(["disabled"])
        self.worker=threading.Thread(target=self.worker_wrapper,args=(target,),daemon=True); self.worker.start()

    def worker_wrapper(self,target):
        try: target()
        finally: self.ui_queue.put(("worker_done",None))

    # ---------- UI log ----------
    def post_log(self,text): self.ui_queue.put(("log",sanitize_listener_text(text)))
    def post_status(self,text,progress=None): self.ui_queue.put(("status",(text,progress)))
    def log(self,text):
        stamp=time.strftime("%H:%M:%S")
        safe = sanitize_listener_text(text)
        line=f"[{stamp}] {safe}\n"
        try:
            self.txt_log.insert("end",line)
            self.txt_log.see("end")
        except Exception as exc:
            # Never let malformed external-process output kill the UI queue.
            fallback=f"[{stamp}] [LISTENER SANITIZE ERROR: {type(exc).__name__}]\n"
            try: self.txt_log.insert("end",fallback); self.txt_log.see("end")
            except Exception: pass
            line=fallback
        self.last_report += line

    def pump_ui_queue(self):
        try:
            while True:
                kind,payload=self.ui_queue.get_nowait()
                try:
                    if kind=="log": self.log(payload)
                    elif kind=="status":
                        text,prog=payload; self.var_status.set(text)
                        if prog is not None: self.var_progress.set(prog)
                    elif kind=="converter_info": self.var_converter_info.set(sanitize_listener_text(payload))
                    elif kind=="refresh_preview": self.preview_command(silent=True)
                    elif kind=="worker_done":
                        self.btn_convert.state(["!disabled"]); self.btn_processor.state(["!disabled"])
                except Exception:
                    # A bad external-output message must not stop future UI updates.
                    try: self.log("SC CC UI QUEUE WARNING\n"+traceback.format_exc())
                    except Exception: pass
        except queue.Empty:
            pass
        self.after(75,self.pump_ui_queue)

    def write_session_log(self):
        text=self.last_report
        if not text: return
        name=time.strftime("SC_CGF_%Y%m%d_%H%M%S.log")
        try: (LOG_DIR/name).write_text(text,encoding="utf-8")
        except Exception: pass

    def copy_report(self):
        self.clipboard_clear(); self.clipboard_append(self.last_report or self.txt_log.get("1.0","end-1c")); self.update()
        self.var_status.set("Report copied to clipboard")
    def clear_log(self): self.txt_log.delete("1.0","end"); self.last_report=""; self.var_progress.set(0); self.var_status.set("Ready")
    def open_output(self):
        p=Path(self.var_output.get().strip() or DEFAULT_OUTPUT); p.mkdir(parents=True,exist_ok=True)
        try: os.startfile(str(p))
        except Exception as e: messagebox.showerror(APP_TITLE,str(e))

    def create_desktop_shortcut(self):
        if os.name != "nt":
            messagebox.showinfo(APP_TITLE, "Desktop shortcut creation is available on Windows.")
            return
        launcher = ROOT / "START_SC_CGF_Converter.vbs"
        if not launcher.exists():
            messagebox.showerror(APP_TITLE, f"Launcher was not found:\n{launcher}")
            return
        desktop = windows_desktop_folder()
        desktop.mkdir(parents=True, exist_ok=True)
        shortcut = desktop / "SC CC - Star Citizen CGF Converter.lnk"
        icon = APP_ICON_ICO if APP_ICON_ICO.exists() else launcher
        # Target WScript directly so the shortcut never opens a command window.
        wscript = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
        ps = (
            "$ws=New-Object -ComObject WScript.Shell;"
            f"$s=$ws.CreateShortcut('{str(shortcut).replace(chr(39), chr(39)*2)}');"
            f"$s.TargetPath='{str(wscript).replace(chr(39), chr(39)*2)}';"
            f"$s.Arguments='\"{str(launcher).replace(chr(39), chr(39)*2)}\"';"
            f"$s.WorkingDirectory='{str(ROOT).replace(chr(39), chr(39)*2)}';"
            f"$s.IconLocation='{str(icon).replace(chr(39), chr(39)*2)},0';"
            "$s.Description='SC CC - Star Citizen CGF Converter development host';"
            "$s.Save();"
        )
        try:
            cp = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True, text=True, errors="replace", timeout=20, **hidden_process_kwargs()
            )
            if cp.returncode != 0 or not shortcut.exists():
                raise RuntimeError((cp.stderr or cp.stdout or f"PowerShell exit {cp.returncode}").strip())
            self.var_status.set("Desktop shortcut created")
            self.log(f"DESKTOP SHORTCUT CREATED: {shortcut}")
            messagebox.showinfo(APP_TITLE, f"Desktop shortcut created:\n{shortcut}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not create desktop shortcut.\n\n{exc}")

    def on_close(self):
        try: self.save_settings()
        finally: self.destroy()


if __name__ == "__main__":
    App().mainloop()
