"""Portable, single-file native CGF Converter GUI. Python 3 + Tkinter required.
No processors, profiles, external presets or companion Python files. Folder preferences are saved beside this script.
Select the updated native cgf-converter.exe; its -folder and -out flags are used.
"""
from pathlib import Path
import os
import json
import queue
import re
import subprocess
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

TITLE = 'SC CGF Converter 0.4.3 â€” Batch Export'
ROOT = Path(__file__).resolve().parent
PATH_SETTINGS = ROOT / 'SC_CGF_Converter_Folders.json'
FORMATS = {'USDA': '-usd', 'DAE (legacy)': '-dae', 'GLTF': '-gltf', 'GLB': '-glb'}
FILTERS = {
    'Normal batch (.cgf, .cga, .skin, .chr)': 'cgf,cga,skin,chr',
    'Static Files (.cgf, .skin)': 'cgf,skin',
    'All Star Citizen Files': 'all',
    'Animated Files (.cga, .skin, .chr)': 'animated',
    '.skin/chr (landing gear, armor, weapons)': 'skin,chr',
}
HELP = '''BATCH EXPORT / LIVE LISTENER
1. Select the updated native cgf-converter.exe from the Windows folder of the native batch package.
2. Choose an Input File or Input Folder.
3. Select the extracted game Data folder containing Objects and animation dependencies.
4. Choose a different Output folder.
5. For normal exports leave Format = USDA, Animations off, and Workers = 2.
6. Click EXPORT.

Folder batches use one converter process with two parallel workers. Include subfolders and Preserve folder structure are on by default. Output paths preserve the hierarchy below Game/Data root. Selecting Data/Objects/Ships/ANVL/Gear as Input Folder exports into Output/Objects/Ships/ANVL/Gear. The same rule applies to a single input file. Turning preservation off exports directly into Output.

Processor is permanently None. This GUI never imports or executes processor modules and does not read old settings, Profiles, Presets or Modules folders.

File filter selects which extensions to attempt in a folder. The animated filter does not automatically enable animation loading: turn on Include animations when you want external clips. Format variants remain subject to the converter's decoder support.

Unsplit DDS textures is optional and off by default. Enable it if you need split DDS files combined. It can add processing work.

The Export destination line shows the required folder before you run. Each primary export is checked in that folder after conversion; missing or unchanged files are reported as failures. Matching CHR/SKIN asset names receive type suffixes (for example argo_atls_chr.usda and argo_atls_skin.usda); unique names stay unchanged. The Listener is visible by default and shows timestamped live output, per-file timings and a heartbeat if the converter is silent. Running exports show elapsed time and time since the last converter output. Stop terminates this GUI's converter process. Completed exports show a full 100% progress bar. Detailed logging is optional and off by default. A successful exit alone does not validate the model in 3ds Max.

When a .cga and .cgf would export to the same filename, CGA keeps the base name and only CGF receives _cgf (for example optic.usda and optic_cgf.usda). Unique CGF names are unchanged. The GUI first verifies native collision-safe output and then publishes the CGA primary under its base name. Referenced companion files keep their native names. Other collision types retain deterministic type/number suffixes. Use the converter EXE included with this package; the old strict-name build rejects conflicts.

Converter, input, Game/Data and output paths are remembered between sessions in SC_CGF_Converter_Folders.json beside the script. Each dialog starts in its own last-used folder; Save Log remembers its folder too. Cancelling a dialog leaves the saved selection unchanged.

Check Converter displays the actual selected executable version and supported options. Preview Command shows the exact job without running it. Copy Report copies the listener. Save Log writes a text file you choose.

This single Python file requires Python 3 with Tkinter and the native converter EXE. It does not include the converter inside the GUI. Close the old conversion before exporting to the same destination.'''


def hidden_process_kwargs():
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


def parse_flags(text):
    flags = set(re.findall(r'(?<![\w])-[a-z][a-z0-9]*', text.lower()))
    # Native batch build 2.0.1-sc-batch.1 implements -out but omits it from usage.
    # The paired -folder/-timings options identify that build's capabilities.
    if {'-folder', '-timings'}.issubset(flags):
        flags.add('-out')
    return flags


def build_command(executable, source, game, output, fmt, types, recursive=True,
                  preserve=True, animations=False, unsplit=False, workers=2):
    exe, inp, data, out = map(lambda p: Path(p).expanduser().resolve(), (executable, source, game, output))
    if not exe.is_file():
        raise ValueError('Select an existing cgf-converter.exe.')
    if not inp.exists():
        raise ValueError('Select an existing input file or folder.')
    if not data.is_dir():
        raise ValueError('Select the extracted game Data folder.')
    if out == inp or (inp.is_file() and out == inp.parent):
        raise ValueError('Choose an output folder different from the input folder.')
    if out.exists() and not out.is_dir():
        raise ValueError('Output must be a folder.')
    if not 1 <= int(workers) <= 32:
        raise ValueError('Workers must be between 1 and 32.')
    if preserve:
        source_dir = inp if inp.is_dir() else inp.parent
        try:
            relative_dir = source_dir.relative_to(data)
        except ValueError:
            raise ValueError('To preserve folders, the input must be inside Game/Data root. Choose the correct root or turn preservation off.') from None
        out = out / relative_dir
    cmd = [str(exe)]
    if inp.is_dir():
        cmd += ['-folder', str(inp), '-types', types]
        if not recursive:
            cmd += ['-toponly']
        if not preserve:
            cmd += ['-flat']
    else:
        if inp.suffix.lower() not in {'.cgf', '.cga', '.chr', '.skin', '.anim', '.dba'}:
            raise ValueError('Supported input types: CGF, CGA, CHR, SKIN, ANIM, DBA.')
        cmd += [str(inp)]
    cmd += ['-objectdir', str(data), '-out', str(out), FORMATS[fmt],
            '-mt', str(int(workers)), '-timings', '-loglevel', 'info']
    if animations:
        cmd.append('-anim')
    if unsplit:
        cmd.append('-ut')
    return cmd


def export_plan(command, *, native_names=False):
    """Expected exports. Native names are verified before applying GUI naming policy."""
    output = Path(command[command.index('-out') + 1])
    extensions = {'USDA': '.usda', 'DAE (legacy)': '.dae', 'GLTF': '.gltf', 'GLB': '.glb'}
    extension = next(extensions[name] for name, flag in FORMATS.items() if flag in command)
    if '-folder' not in command:
        inputs = [Path(command[1])]
        root = inputs[0].parent
    else:
        root = Path(command[command.index('-folder') + 1])
        types = command[command.index('-types') + 1]
        types = {'all': 'cgf,cga,skin,chr,anim,dba', 'animated': 'cga,skin,chr'}.get(types, types)
        allowed = {'.' + value.strip().lstrip('.').lower() for value in types.split(',')}
        inputs = []
        for directory, dirs, filenames in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(directory)/name).is_symlink() and (Path(directory)/name).resolve() != output.resolve()]
            for name in filenames:
                path = Path(directory)/name
                if path.suffix.lower() in allowed and not path.is_symlink():
                    inputs.append(path)
            if '-toponly' in command:
                break
    if not inputs:
        raise ValueError('No matching input assets were found.')
    groups = {}
    for source in sorted(inputs, key=lambda p: (str(p).upper(), str(p))):
        relative = source.relative_to(root) if '-folder' in command and '-flat' not in command else Path(source.name)
        destination = output / relative.with_suffix(extension)
        groups.setdefault(str(destination).casefold(), []).append((source, destination))
    # Only an exact CGA/CGF output pair gives the CGA the unsuffixed name.
    # Other collisions keep the native deterministic type/number suffix policy.
    cga_names = {}
    if not native_names:
        for group in groups.values():
            if len(group) == 2 and {src.suffix.lower() for src, _ in group} == {'.cga', '.cgf'}:
                for source, destination in group:
                    if source.suffix.lower() == '.cga':
                        cga_names[source] = destination
    used = {key for key, group in groups.items() if len(group) == 1}
    plan = []
    for group in groups.values():
        if len(group) == 1:
            plan.extend(group)
            continue
        if '-strictnames' in command:
            raise ValueError('Two inputs would overwrite the same export: ' + str(group[0][1]))
        for source, destination in group:
            basis = source.stem + '_' + source.suffix[1:].lower()
            candidate = destination.with_name(basis + extension)
            number = 2
            while str(candidate).casefold() in used:
                candidate = destination.with_name(basis + '_' + str(number) + extension)
                number += 1
            used.add(str(candidate).casefold())
            plan.append((source, candidate))
    return [(source, cga_names.get(source, destination)) for source, destination in plan]


def file_stamp(path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size) if path.is_file() and stat.st_size else None
    except FileNotFoundError:
        return None


def verify_exports(plan, before):
    missing = [dest for _, dest in plan if file_stamp(dest) is None or file_stamp(dest) == before.get(str(dest))]
    if missing:
        preview = '\n'.join(str(path) for path in missing[:4])
        raise RuntimeError(f'{len(missing)} expected export(s) were not updated in their required folder:\n{preview}\nThe batch was not marked successful. See the Listener for the converter command and output path.')
    return len(plan)


def finalize_export_names(native_plan, final_plan, log=None):
    """Publish the CGA primary under its base name after native output verification.

    Companion assets keep the native filenames referenced inside the export.
    Inputs and decoded content are never renamed or rewritten.
    """
    native_by_source = dict(native_plan)
    if len(native_by_source) != len(final_plan) or set(native_by_source) != {src for src, _ in final_plan}:
        raise RuntimeError('Native and final export plans do not contain the same inputs.')
    targets = [str(dest).casefold() for _, dest in final_plan]
    if len(targets) != len(set(targets)):
        raise RuntimeError('Final output names are not unique.')
    moves = [(source, native_by_source[source], dest) for source, dest in final_plan
             if native_by_source[source] != dest]
    # Check the entire publication plan before renaming any primary export.
    native_targets = {str(dest).casefold() for _, dest in native_plan}
    for source, original, dest in moves:
        if source.suffix.lower() != '.cga' or file_stamp(original) is None:
            raise RuntimeError('Missing verified CGA export: ' + str(original))
        if str(dest).casefold() in native_targets:
            raise RuntimeError('CGA base name would replace another native export: ' + str(dest))
    for source, original, dest in moves:
        original.replace(dest)
        if log is not None:
            log('CGA/CGF CONFLICT: CGA keeps ' + str(dest) + '; CGF receives _cgf. Companion names are retained.')


def load_folder_preferences(path=PATH_SETTINGS):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items()
                if key in ('exe', 'source', 'game', 'output', 'log') and isinstance(value, str)}
    except (OSError, ValueError):
        return {}


def save_folder_preferences(data, path=PATH_SETTINGS):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def dialog_folder(value):
    # Use a valid ancestor if a drive/folder saved on another machine is absent.
    if value:
        candidate = Path(value).expanduser()
        while not candidate.is_dir():
            if candidate.parent == candidate:
                return str(ROOT)
            candidate = candidate.parent
        return str(candidate)
    return str(ROOT)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.timer, self.popup = widget, text, None, None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(500, self.show)
    def show(self):
        self.timer = None
        self.popup = tk.Toplevel(self.widget)
        self.popup.wm_overrideredirect(True)
        self.popup.geometry(f'+{self.widget.winfo_rootx()+12}+{self.widget.winfo_rooty()+self.widget.winfo_height()+4}')
        ttk.Label(self.popup, text=self.text, wraplength=400, padding=8, relief='solid').pack()
    def hide(self, event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry('1120x850')
        self.minsize(980, 700)
        self.events = queue.Queue()
        self.running = False
        self.process = None
        self.process_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.started_at = None
        self.last_output_at = None
        self.last_heartbeat = None
        self.completed = 0
        self.total = 0
        self.report_lines = []
        self.folder_preferences = load_folder_preferences()
        self.folder_save_error = False
        saved_exe = self.folder_preferences.get('exe', '')
        self.exe = tk.StringVar(value=saved_exe if saved_exe and Path(saved_exe).is_file() else self.find_converter())
        self.source = tk.StringVar(value=self.folder_preferences.get('source', ''))
        self.game = tk.StringVar(value=self.folder_preferences.get('game', ''))
        self.output = tk.StringVar(value=self.folder_preferences.get('output', ''))
        self.fmt = tk.StringVar(value='USDA')
        self.types = tk.StringVar(value=next(iter(FILTERS)))
        self.recursive = tk.BooleanVar(value=True)
        self.preserve = tk.BooleanVar(value=True)
        self.animations = tk.BooleanVar(value=False)
        self.unsplit = tk.BooleanVar(value=False)
        self.verbose = tk.BooleanVar(value=False)
        self.workers = tk.IntVar(value=2)
        self.status = tk.StringVar(value='Ready â€” Processor: None')
        self.activity = tk.StringVar(value='Idle')
        self.destination = tk.StringVar(value='Export destination: choose input, Game/Data root and output.')
        self.converter_info = tk.StringVar(value='Converter not checked')
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text='SC CGF Converter 0.4.3 â€” Batch Export', font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 8))
        self.row(frame, 1, 'Converter EXE', self.exe, [('Browse', self.pick_exe, 'Choose the updated native cgf-converter.exe.'), ('Check Converter', self.check_converter, 'Show the version and usage of the selected executable.')])
        ttk.Label(frame, textvariable=self.converter_info).grid(row=2, column=1, columnspan=2, sticky='w', pady=(0, 6))
        self.row(frame, 3, 'Input asset / folder', self.source, [('Input File', self.pick_file, 'Export one asset.'), ('Input Folder', lambda: self.pick_folder(self.source), 'Export a folder in one native batch process.')])
        self.row(frame, 4, 'Game/Data root', self.game, [('Browse', lambda: self.pick_folder(self.game), 'Choose extracted Data containing Objects and dependencies.')])
        self.row(frame, 5, 'Output folder', self.output, [('Browse', lambda: self.pick_folder(self.output), 'Choose the destination folder.')])
        options = ttk.LabelFrame(frame, text='Export Settings', padding=10)
        options.grid(row=6, column=0, columnspan=3, sticky='ew', pady=(10, 6))
        options.columnconfigure(3, weight=1)
        ttk.Label(options, text='Game').grid(row=0, column=0, sticky='w')
        game_combo = ttk.Combobox(options, values=['StarCitizen'], state='readonly', width=18)
        game_combo.set('StarCitizen')
        game_combo.grid(row=0, column=1, sticky='w', padx=8)
        ttk.Label(options, text='Processor').grid(row=0, column=2, sticky='w', padx=(12, 0))
        proc_combo = ttk.Combobox(options, values=['<None> â€” converter only'], state='readonly', width=35)
        proc_combo.set('<None> â€” converter only')
        proc_combo.grid(row=0, column=3, sticky='w', padx=8)
        Tooltip(proc_combo, 'No processor modules run. Folder preservation and animation options belong to the native converter.')
        ttk.Label(options, text='Format').grid(row=1, column=0, sticky='w', pady=(8, 0))
        ttk.Combobox(options, textvariable=self.fmt, values=list(FORMATS), state='readonly', width=18).grid(row=1, column=1, sticky='w', padx=8, pady=(8, 0))
        ttk.Label(options, text='Preset / file filter').grid(row=1, column=2, padx=(12, 0), pady=(8, 0))
        combo = ttk.Combobox(options, textvariable=self.types, values=list(FILTERS), state='readonly', width=48)
        combo.grid(row=1, column=3, sticky='ew', padx=8, pady=(8, 0))
        Tooltip(combo, 'Filters folder input types. Include animations separately controls clip loading.')
        checks = ttk.Frame(options)
        checks.grid(row=2, column=0, columnspan=4, sticky='w', pady=(10, 0))
        for text, var, helptext in [
            ('Include subfolders', self.recursive, 'On by default. Process nested folders.'),
            ('Preserve Game/Data folders', self.preserve, 'On by default. Keep the hierarchy below Game/Data root.'),
            ('Include animations', self.animations, 'Load external animation clips using the native converter.'),
            ('Unsplit DDS textures', self.unsplit, 'Combine split DDS textures. Optional; off by default.')]:
            w = ttk.Checkbutton(checks, text=text, variable=var)
            w.pack(side='left', padx=(0, 12))
            Tooltip(w, helptext)
        lower = ttk.Frame(options)
        lower.grid(row=3, column=0, columnspan=4, sticky='w', pady=(8, 0))
        ttk.Label(lower, text='Workers').pack(side='left')
        spin = ttk.Spinbox(lower, from_=1, to=32, textvariable=self.workers, width=4)
        spin.pack(side='left', padx=(8, 24))
        Tooltip(spin, 'Start with two workers. Seven concurrent assets can compete for memory and disk access.')
        detail = ttk.Checkbutton(lower, text='Detailed converter logging', variable=self.verbose)
        detail.pack(side='left')
        Tooltip(detail, 'Enable before export for debug output from the converter. The normal listener is always available.')
        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=3, sticky='ew', pady=6)
        self.export = self.button(actions, 'EXPORT', self.start, 'Run one native batch. No external Python processor runs.')
        self.stop_button = self.button(actions, 'Stop', self.stop, 'Stop the converter launched by this window. Existing files remain.')
        self.stop_button.configure(state='disabled')
        self.button(actions, 'Preview Command', self.preview_command, 'Show the exact converter command without executing it.')
        self.button(actions, 'Open Output', self.open_output, 'Open the output folder.')
        self.button(actions, 'Help', self.help, 'Show instructions for settings and the listener.')
        ttk.Label(frame, textvariable=self.destination, wraplength=1050).grid(row=8, column=0, columnspan=3, sticky='w', pady=(3, 4))
        ttk.Label(frame, textvariable=self.status, wraplength=1050).grid(row=9, column=0, columnspan=3, sticky='w')
        ttk.Label(frame, textvariable=self.activity).grid(row=10, column=0, columnspan=3, sticky='w', pady=(2, 4))
        self.progress = ttk.Progressbar(frame, mode='determinate', maximum=100, value=0)
        self.progress.grid(row=11, column=0, columnspan=3, sticky='ew', pady=(0, 5))
        self.command = tk.Text(frame, height=2, wrap='word', state='disabled', font=('Consolas', 9))
        self.command.grid(row=12, column=0, columnspan=3, sticky='ew')
        listener = ttk.LabelFrame(frame, text='Listener â€” live converter output', padding=5)
        listener.grid(row=13, column=0, columnspan=3, sticky='nsew', pady=(8, 0))
        listener.columnconfigure(0, weight=1)
        listener.rowconfigure(0, weight=1)
        self.log = tk.Text(listener, height=13, wrap='word', state='disabled', font=('Consolas', 9))
        self.log.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(listener, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.log.configure(yscrollcommand=scroll.set)
        tools = ttk.Frame(frame)
        tools.grid(row=14, column=0, columnspan=3, sticky='ew', pady=(6, 0))
        self.button(tools, 'Copy Report', self.copy_report, 'Copy the complete listener output to the clipboard.')
        self.button(tools, 'Save Log', self.save_log, 'Save all listener output to a text file.')
        self.button(tools, 'Clear Listener', self.clear_listener, 'Clear displayed messages after a run.')
        frame.rowconfigure(13, weight=1)
        for var in (self.source, self.game, self.output, self.preserve):
            var.trace_add('write', self.refresh_destination)
        for var in (self.exe, self.source, self.game, self.output):
            var.trace_add('write', self.remember_paths)
        self.refresh_destination()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.drain)
        self.after(1000, self.tick)
        self.append_log('Ready. Processor: None. Select the native converter and paths, then Preview Command or EXPORT.')

    @staticmethod
    def find_converter():
        for p in (ROOT/'cgf-converter.exe', ROOT/'Windows'/'cgf-converter.exe', ROOT.parent/'Windows'/'cgf-converter.exe'):
            if p.is_file():
                return str(p)
        return ''

    def button(self, parent, text, command, tip):
        w = ttk.Button(parent, text=text, command=command)
        w.pack(side='left', padx=(0, 8))
        Tooltip(w, tip)
        return w

    def row(self, frame, row, label, var, buttons):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
        ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky='ew', pady=4)
        actions = ttk.Frame(frame)
        actions.grid(row=row, column=2, sticky='w', padx=(8, 0))
        for text, command, tip in buttons:
            self.button(actions, text, command, tip)

    def remember_paths(self, *args):
        self.folder_preferences.update(exe=self.exe.get(), source=self.source.get(),
                                       game=self.game.get(), output=self.output.get())
        try:
            save_folder_preferences(self.folder_preferences)
            self.folder_save_error = False
        except OSError as error:
            if not self.folder_save_error:
                self.append_log('Could not save folder preferences beside the script: ' + str(error))
                self.folder_save_error = True

    def pick_exe(self):
        p = filedialog.askopenfilename(title='Select native cgf-converter.exe', initialdir=dialog_folder(self.exe.get()), filetypes=[('Converter', '*.exe'), ('All files', '*.*')])
        if p:
            self.exe.set(p)
            self.converter_info.set('Converter path changed â€” click Check Converter')

    def pick_file(self):
        p = filedialog.askopenfilename(title='Input asset', initialdir=dialog_folder(self.source.get()), filetypes=[('CryEngine assets', '*.cgf *.cga *.chr *.skin *.anim *.dba'), ('All files', '*.*')])
        if p:
            self.source.set(p)

    def pick_folder(self, var):
        p = filedialog.askdirectory(title='Select folder', initialdir=dialog_folder(var.get()), mustexist=False if var is self.output else True)
        if p:
            var.set(p)

    def refresh_destination(self, *args):
        if not all(v.get().strip() for v in (self.source, self.game, self.output)):
            self.destination.set('Export destination: choose input, Game/Data root and output.')
            return
        try:
            source = Path(self.source.get()).expanduser().resolve()
            game = Path(self.game.get()).expanduser().resolve()
            target = Path(self.output.get()).expanduser().resolve()
            if self.preserve.get():
                parent = source if source.is_dir() else source.parent
                target = target / parent.relative_to(game)
            self.destination.set('Export destination: ' + str(target))
        except ValueError:
            self.destination.set('Input must be inside Game/Data root to preserve folders.')

    def help(self):
        popup = tk.Toplevel(self)
        popup.title('Help â€” CGF Converter')
        popup.geometry('760x600')
        text = tk.Text(popup, wrap='word', padx=14, pady=14)
        text.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(popup, command=text.yview)
        scroll.pack(side='right', fill='y')
        text.configure(yscrollcommand=scroll.set)
        text.insert('1.0', HELP)
        text.configure(state='disabled')

    def open_output(self):
        path = Path(self.output.get()).expanduser()
        if not self.output.get().strip() or not path.is_dir():
            messagebox.showinfo(TITLE, 'Choose an existing output folder first.')
            return
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            subprocess.Popen(['open' if __import__('sys').platform == 'darwin' else 'xdg-open', str(path)])

    def make_command(self):
        paths = [v.get().strip() for v in (self.exe, self.source, self.game, self.output)]
        if not all(paths):
            raise ValueError('Choose the converter, input, Game/Data root, and output folder.')
        cmd = build_command(*paths, self.fmt.get(), FILTERS[self.types.get()], self.recursive.get(), self.preserve.get(), self.animations.get(), self.unsplit.get(), self.workers.get())
        if self.verbose.get():
            cmd[cmd.index('-loglevel') + 1] = 'debug'
        return cmd, paths[2]

    def show_command(self, cmd):
        self.command.configure(state='normal')
        self.command.delete('1.0', 'end')
        self.command.insert('1.0', subprocess.list2cmdline(cmd))
        self.command.configure(state='disabled')

    def preview_command(self):
        try:
            cmd, cwd = self.make_command()
            self.show_command(cmd)
            plan = export_plan(cmd)
            self.append_log(f'PREVIEW: {len(plan)} input asset(s). First required export: {plan[0][1]}')
            self.append_log(subprocess.list2cmdline(cmd))
        except Exception as e:
            messagebox.showwarning(TITLE, str(e))

    def append_log(self, value):
        safe = ''.join(c if ord(c) >= 32 or c in '\n\t' else ' ' for c in str(value))
        line = '[' + datetime.now().strftime('%H:%M:%S') + '] ' + safe
        self.report_lines.append(line)
        self.log.configure(state='normal')
        self.log.insert('end', line + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 5000:
            self.log.delete('1.0', '1000.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def copy_report(self):
        self.clipboard_clear()
        self.clipboard_append('\n'.join(self.report_lines))
        self.update_idletasks()

    def save_log(self):
        path = filedialog.asksaveasfilename(title='Save listener log', initialdir=dialog_folder(self.folder_preferences.get('log', self.output.get())), defaultextension='.txt', initialfile='CGF_Converter_Log.txt', filetypes=[('Text', '*.txt')])
        if path:
            try:
                Path(path).write_text('\n'.join(self.report_lines) + '\n', encoding='utf-8')
                self.folder_preferences['log'] = str(Path(path).parent)
                self.remember_paths()
            except OSError as e:
                messagebox.showerror(TITLE, str(e))

    def clear_listener(self):
        if self.running:
            return
        self.report_lines.clear()
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    def start(self):
        if self.running:
            return
        try:
            cmd, cwd = self.make_command()
            self.show_command(cmd)
        except Exception as e:
            messagebox.showwarning(TITLE, str(e))
            return
        self.begin_job('Checking converterâ€¦ Processor: None')
        self.append_log('EXPORT START: ' + subprocess.list2cmdline(cmd))
        threading.Thread(target=self.work, args=(cmd, cwd), daemon=True).start()

    def begin_job(self, status):
        self.running = True
        self.cancel_event.clear()
        self.started_at = time.monotonic()
        self.last_output_at = self.started_at
        self.last_heartbeat = self.started_at
        self.completed = self.total = 0
        self.progress.stop()
        self.progress.configure(mode='indeterminate', value=0)
        self.progress.start(12)
        self.export.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.status.set(status)

    def check_converter(self):
        if self.running:
            return
        exe = self.exe.get().strip()
        if not Path(exe).is_file():
            messagebox.showwarning(TITLE, 'Select an existing converter executable first.')
            return
        self.begin_job('Checking converter version and usageâ€¦')
        def check():
            try:
                self.probe(exe)
                self.events.put(('checked', 'Converter check complete'))
            except Exception as e:
                self.events.put(('error', str(e)))
        threading.Thread(target=check, daemon=True).start()

    def probe(self, exe):
        cp = subprocess.run([exe, '-usage'], capture_output=True, text=True, errors='replace', timeout=30, **hidden_process_kwargs())
        usage = (cp.stdout or '') + (cp.stderr or '')
        version = next((line.strip() for line in usage.splitlines() if 'converter v' in line.lower()), 'Converter version not advertised')
        self.events.put(('version', version))
        self.events.put(('log', 'CONVERTER: ' + version + ' | ' + exe))
        self.events.put(('log', usage.strip()))
        return parse_flags(usage)

    def work(self, cmd, cwd):
        try:
            flags = self.probe(cmd[0])
            if self.cancel_event.is_set():
                self.events.put(('cancelled', 'Stopped before conversion'))
                return
            missing = sorted({x for x in cmd[1:] if x.startswith('-')} - flags)
            if missing:
                raise RuntimeError('Selected converter does not support: ' + ', '.join(missing) + '. Select Windows/cgf-converter.exe from the native batch package. StarFab v1.6 is incompatible with these options.')
            plan = export_plan(cmd)
            native_plan = export_plan(cmd, native_names=True)
            renamed = [(source, dest) for source, dest in native_plan if source.stem != dest.stem]
            if renamed and '-strictnames' not in flags:
                raise RuntimeError('This batch needs the updated collision-safe converter. Select Windows/cgf-converter.exe from the new package; the older converter stops on matching .chr/.skin names.')
            for source, dest in renamed:
                self.events.put(('log', 'COLLISION NAME: ' + str(source) + ' -> ' + str(dest)))
            before = {str(dest): file_stamp(dest) for _, dest in plan}
            native_before = {str(dest): file_stamp(dest) for _, dest in native_plan}
            self.events.put(('plan', len(plan)))
            self.events.put(('log', 'EXPECTED FIRST EXPORT: ' + str(plan[0][1])))
            self.events.put(('log', 'OUTPUT BASE: ' + cmd[cmd.index('-out') + 1]))
            self.events.put(('status', 'Exporting with native converter â€” Processor: None'))
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1, cwd=cwd, **hidden_process_kwargs()) as proc:
                with self.process_lock:
                    self.process = proc
                    if self.cancel_event.is_set():
                        proc.terminate()
                finished = 0
                for line in proc.stdout:
                    text = line.rstrip()
                    self.events.put(('log', text))
                    if '[timing]' in text and ': export ' in text:
                        finished += 1
                        self.events.put(('progress', (finished, len(plan))))
                    elif '[timing]' in text and ': loaded in ' in text:
                        self.events.put(('status', 'Loaded: ' + text.split('[timing]', 1)[1].strip()))
                code = proc.wait()
            if self.cancel_event.is_set():
                self.events.put(('cancelled', 'Export stopped; partial outputs may remain'))
                return
            if code:
                raise RuntimeError(f'Converter returned {code}. See the Listener for its errors.')
            verify_exports(native_plan, native_before)
            finalize_export_names(native_plan, plan, lambda text: self.events.put(('log', text)))
            count = verify_exports(plan, before)
            self.events.put(('done', f'Completed â€” verified {count} asset(s) in their required folders'))
        except Exception as e:
            self.events.put(('cancelled' if self.cancel_event.is_set() else 'error', str(e)))
        finally:
            with self.process_lock:
                self.process = None

    def stop(self):
        if not self.running:
            return
        self.cancel_event.set()
        self.stop_button.configure(state='disabled')
        self.status.set('Stopping converterâ€¦')
        self.append_log('STOP REQUESTED')
        with self.process_lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()

    @staticmethod
    def duration(seconds):
        seconds = max(0, int(seconds))
        return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'

    def tick(self):
        if self.running and self.started_at is not None:
            now = time.monotonic()
            elapsed = now - self.started_at
            silence = now - self.last_output_at
            self.activity.set(f'RUNNING | elapsed {self.duration(elapsed)} | completed {self.completed}/{self.total or "?"} | last converter output {int(silence)}s ago')
            if silence >= 30 and now - self.last_heartbeat >= 30:
                self.append_log(f'Waiting: converter has not emitted output for {int(silence)}s. Elapsed {self.duration(elapsed)}. The job is still active; Stop is available.')
                self.last_heartbeat = now
        self.after(1000, self.tick)

    def finish_job(self, kind, value):
        elapsed = time.monotonic() - self.started_at if self.started_at is not None else 0
        self.running = False
        self.progress.stop()
        self.progress.configure(mode='determinate', value=100 if kind == 'done' else 0)
        self.export.configure(state='normal')
        self.stop_button.configure(state='disabled')
        self.status.set(value)
        self.activity.set(('COMPLETED' if kind in {'done', 'checked'} else 'STOPPED' if kind == 'cancelled' else 'FAILED') + ' | elapsed ' + self.duration(elapsed))
        self.append_log(value + ' | elapsed ' + self.duration(elapsed))
        if kind == 'error':
            messagebox.showerror(TITLE, value)

    def drain(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.last_output_at = time.monotonic()
                self.append_log(value)
            elif kind == 'version':
                self.converter_info.set(value)
            elif kind == 'plan':
                self.total = value
            elif kind == 'progress':
                self.completed, self.total = value
                self.progress.stop()
                self.progress.configure(mode='determinate', value=min(100, 100*self.completed/max(1, self.total)))
            elif kind == 'status':
                self.status.set(value)
            else:
                self.finish_job(kind, value)
        self.after(100, self.drain)

    def close(self):
        if self.running:
            messagebox.showinfo(TITLE, 'Click Stop and wait for the converter to exit before closing.')
            return
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
