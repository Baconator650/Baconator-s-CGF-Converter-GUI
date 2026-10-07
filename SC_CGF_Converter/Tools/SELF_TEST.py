from pathlib import Path
import importlib.util,json,py_compile,runpy
ROOT=Path(__file__).resolve().parents[1]
for p in [ROOT/'SC_CGF_Converter.py',ROOT/'SC_CGF_Converter.pyw',*sorted((ROOT/'Modules').rglob('*.py'))]:
    py_compile.compile(str(p),doraise=True)
for p in [*sorted((ROOT/'Profiles').glob('*.json')),*sorted((ROOT/'Presets').glob('*.json'))]:
    json.loads(p.read_text())
p=ROOT/'Modules/Stable/sc_native_animation_export.py'
spec=importlib.util.spec_from_file_location('native_check',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m._math_checks()
for name in ['BATCH_SELF_TEST.py','UI_SELF_TEST.py','PRESET_SELF_TEST.py']:
    runpy.run_path(str(ROOT/'Tools'/name),run_name='__main__')
print('PASS: public package syntax, metadata, transform math, batch, UI-state and preset checks')
