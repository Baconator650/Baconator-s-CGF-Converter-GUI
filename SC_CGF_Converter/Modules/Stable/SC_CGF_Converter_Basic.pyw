"""Portable, single-file native CGF Converter GUI. Python 3 + Tkinter required.
No processors, profiles, external presets, settings, or companion Python files.
Select the updated native cgf-converter.exe; its -folder and -out flags are used.
"""
from pathlib import Path
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

TITLE = 'SC CGF Converter — Basic 1.1'
ROOT = Path(__file__).resolve().parent
FORMATS = {'USDA': '-usd', 'DAE (legacy)': '-dae', 'GLTF': '-gltf', 'GLB': '-glb'}
FILTERS = {
    'Normal batch (.cgf, .cga, .skin, .chr)': 'cgf,cga,skin,chr',
    'All Star Citizen Files': 'all',
    'Animated Files (.cga, .skin, .chr)': 'animated',
    '.skin/chr (landing gear, armor, weapons)': 'skin,chr',
}
HELP = '''BASIC EXPORT
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

Show log displays converter messages and per-file load/export timings. Diagnostics are hidden by default. A successful exit alone does not validate the model in 3ds Max.

Output name collisions are rejected by the native converter. Use a narrower input folder/filter if two assets would produce the same output name.

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
        self.geometry('970x470')
        self.minsize(850, 460)
        self.events = queue.Queue()
        self.running = False
        self.exe = tk.StringVar(value=self.find_converter())
        self.source = tk.StringVar()
        self.game = tk.StringVar()
        self.output = tk.StringVar()
        self.fmt = tk.StringVar(value='USDA')
        self.types = tk.StringVar(value=next(iter(FILTERS)))
        self.recursive = tk.BooleanVar(value=True)
        self.preserve = tk.BooleanVar(value=True)
        self.animations = tk.BooleanVar(value=False)
        self.unsplit = tk.BooleanVar(value=False)
        self.show_log = tk.BooleanVar(value=False)
        self.workers = tk.IntVar(value=2)
        self.status = tk.StringVar(value='Ready — Processor: None')
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        self.row(frame, 0, 'Converter EXE', self.exe, [('Browse', self.pick_exe, 'Choose the updated native cgf-converter.exe.')])
        self.row(frame, 1, 'Input asset / folder', self.source, [('Input File', self.pick_file, 'Export one asset.'), ('Input Folder', lambda: self.pick_folder(self.source), 'Export a folder in one native batch process.')])
        self.row(frame, 2, 'Game/Data root', self.game, [('Browse', lambda: self.pick_folder(self.game), 'Choose extracted Data containing Objects and dependencies.')])
        self.row(frame, 3, 'Output folder', self.output, [('Browse', lambda: self.pick_folder(self.output), 'Choose the destination folder.')])
        options = ttk.LabelFrame(frame, text='Basic export settings', padding=10)
        options.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(12, 8))
        options.columnconfigure(3, weight=1)
        ttk.Label(options, text='Format').grid(row=0, column=0, sticky='w')
        ttk.Combobox(options, textvariable=self.fmt, values=list(FORMATS), state='readonly', width=16).grid(row=0, column=1, padx=(8, 18))
        ttk.Label(options, text='Folder file filter').grid(row=0, column=2)
        combo = ttk.Combobox(options, textvariable=self.types, values=list(FILTERS), state='readonly', width=43)
        combo.grid(row=0, column=3, padx=8, sticky='ew')
        Tooltip(combo, 'Filters folder inputs. Animation loading is controlled by the checkbox below.')
        checks = ttk.Frame(options)
        checks.grid(row=1, column=0, columnspan=4, sticky='w', pady=(12, 0))
        for text, var, helptext in [
            ('Include subfolders', self.recursive, 'On by default. Process nested folders.'),
            ('Preserve Game/Data folders', self.preserve, 'On by default. Keep the input hierarchy below Game/Data root, including Objects and its subfolders.'),
            ('Include animations', self.animations, 'Load external animation clips using the native converter. Off for normal exports.'),
            ('Unsplit DDS textures', self.unsplit, 'Combine split DDS textures. Optional; off by default.')]:
            w = ttk.Checkbutton(checks, text=text, variable=var)
            w.pack(side='left', padx=(0, 12))
            Tooltip(w, helptext)
        lower = ttk.Frame(options)
        lower.grid(row=2, column=0, columnspan=4, sticky='w', pady=(10, 0))
        ttk.Label(lower, text='Workers').pack(side='left')
        spin = ttk.Spinbox(lower, from_=1, to=32, textvariable=self.workers, width=4)
        spin.pack(side='left', padx=(8, 24))
        Tooltip(spin, 'Maximum concurrent assets. Start with two; higher values use more memory.')
        ttk.Label(lower, text='Processor: None (converter only)').pack(side='left')
        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=3, sticky='ew', pady=8)
        self.export = self.button(actions, 'EXPORT', self.start, 'Run one native converter process. No Python processor is called.')
        self.button(actions, 'Open Output', self.open_output, 'Open the selected output folder.')
        self.button(actions, 'Help', self.help, 'Show setup and export instructions.')
        ttk.Checkbutton(actions, text='Show log', variable=self.show_log, command=self.toggle_log).pack(side='right')
        ttk.Label(frame, textvariable=self.status, wraplength=900).grid(row=6, column=0, columnspan=3, sticky='w', pady=8)
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.grid(row=7, column=0, columnspan=3, sticky='ew')
        self.logframe = ttk.Frame(frame)
        self.logframe.columnconfigure(0, weight=1)
        self.logframe.rowconfigure(0, weight=1)
        self.log = tk.Text(self.logframe, height=14, wrap='word', state='disabled', font=('Consolas', 9))
        self.log.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self.logframe, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.log.configure(yscrollcommand=scroll.set)
        frame.rowconfigure(8, weight=1)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.drain)

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
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=6)
        ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky='ew', pady=6)
        actions = ttk.Frame(frame)
        actions.grid(row=row, column=2, sticky='w', padx=(8, 0))
        for text, command, tip in buttons:
            self.button(actions, text, command, tip)

    def pick_exe(self):
        p = filedialog.askopenfilename(title='Select native cgf-converter.exe', filetypes=[('Converter', '*.exe'), ('All files', '*.*')])
        if p:
            self.exe.set(p)

    def pick_file(self):
        p = filedialog.askopenfilename(title='Input asset', filetypes=[('CryEngine assets', '*.cgf *.cga *.chr *.skin *.anim *.dba'), ('All files', '*.*')])
        if p:
            self.source.set(p)

    def pick_folder(self, var):
        p = filedialog.askdirectory(title='Select folder', mustexist=False if var is self.output else True)
        if p:
            var.set(p)

    def toggle_log(self):
        if self.show_log.get():
            self.logframe.grid(row=8, column=0, columnspan=3, sticky='nsew', pady=(8, 0))
            self.geometry('970x710')
        else:
            self.logframe.grid_remove()
            self.geometry('970x470')

    def help(self):
        popup = tk.Toplevel(self)
        popup.title('Help — Basic CGF Converter')
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

    def start(self):
        if self.running:
            return
        try:
            paths = [v.get().strip() for v in (self.exe, self.source, self.game, self.output)]
            if not all(paths):
                raise ValueError('Choose the converter, input, Game/Data root, and output folder.')
            cmd = build_command(*paths, self.fmt.get(), FILTERS[self.types.get()], self.recursive.get(), self.preserve.get(), self.animations.get(), self.unsplit.get(), self.workers.get())
        except Exception as e:
            messagebox.showwarning(TITLE, str(e))
            return
        self.running = True
        self.export.configure(state='disabled')
        self.status.set('Checking converter… Processor: None')
        self.progress.start(12)
        threading.Thread(target=self.work, args=(cmd, paths[2]), daemon=True).start()

    def work(self, cmd, cwd):
        try:
            probe = subprocess.run([cmd[0], '-usage'], capture_output=True, text=True, errors='replace', timeout=30, **hidden_process_kwargs())
            flags = parse_flags(probe.stdout + probe.stderr)
            required = {x for x in cmd[1:] if x.startswith('-')}
            missing = sorted(required - flags)
            if missing:
                raise RuntimeError('Selected converter does not support: ' + ', '.join(missing) + '. Select Windows/cgf-converter.exe from the updated native batch package. StarFab v1.6 is incompatible with these options.')
            self.events.put(('log', 'OUTPUT BASE: ' + cmd[cmd.index('-out') + 1]))
            self.events.put(('log', subprocess.list2cmdline(cmd)))
            self.events.put(('status', 'Exporting with the native converter… Processor: None'))
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1, cwd=cwd, **hidden_process_kwargs()) as proc:
                for line in proc.stdout:
                    self.events.put(('log', line.rstrip()))
                code = proc.wait()
            if code:
                raise RuntimeError(f'Converter returned {code}. Open Show log for the reported errors.')
            self.events.put(('done', 'Export finished — Processor: None'))
        except Exception as e:
            self.events.put(('error', str(e)))

    def drain(self):
        # Limit each pass so high-volume logs cannot block UI interaction.
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                safe = ''.join(c if ord(c) >= 32 or c in '\n\t' else ' ' for c in value)
                self.log.configure(state='normal')
                self.log.insert('end', safe + '\n')
                if int(self.log.index('end-1c').split('.')[0]) > 5000:
                    self.log.delete('1.0', '1000.0')
                self.log.see('end')
                self.log.configure(state='disabled')
            elif kind == 'status':
                self.status.set(value)
            else:
                self.running = False
                self.progress.stop()
                self.export.configure(state='normal')
                self.status.set(value)
                if kind == 'error':
                    self.show_log.set(True)
                    self.toggle_log()
                    self.log.configure(state='normal')
                    self.log.insert('end', 'ERROR: ' + value + '\n')
                    self.log.configure(state='disabled')
                    messagebox.showerror(TITLE, value)
        self.after(100, self.drain)

    def close(self):
        if self.running:
            messagebox.showinfo(TITLE, 'An export is running. Wait for it to finish before closing this window.')
            return
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
