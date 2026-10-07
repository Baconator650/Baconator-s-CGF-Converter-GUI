import importlib.util,sys,tempfile,json
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('named',root/'SC_CGF_Converter.py');m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
class V:
 def __init__(self,x):self.x=x
 def get(self):return self.x
 def set(self,x):self.x=x
presets={p.stem:json.loads(p.read_text()) for p in (root/'Presets').glob('*.json')}
f=SimpleNamespace(presets=presets,var_preset=V('SC_CHR_SKIN_Animation_USDA'))
f.preset_label=lambda p:m.App.preset_label(f,p);f.selected_preset_id=lambda:m.App.selected_preset_id(f)
assert m.App.current_preset(f)['display_name']=='.skin/chr (landing gear, armor, weapons)'
f.var_preset.set('.skin/chr (landing gear, armor, weapons)');assert f.selected_preset_id()=='SC_CHR_SKIN_Animation_USDA'
with tempfile.TemporaryDirectory(dir='.') as t:
 src=Path(t)/'input';src.mkdir();out=Path(t)/'output'
 for ext in m.ASSET_EXTENSIONS:(src/('asset'+ext)).touch()
 (src/'texture.dds').touch()
 for pid,count in [('SC_CHR_SKIN_Animation_USDA',2),('SC_Animated_Files',3),('SC_All_Star_Citizen_Files',6)]:
  d=presets[pid];jobs=m.plan_batch_jobs(src,out,extensions=d['input_extensions']);assert len(jobs)==count
  assert {p.suffix for p,_ in jobs}==set(d['input_extensions'])
 try:m.plan_batch_jobs(src/'asset.cgf',out,extensions=['.skin','.chr'])
 except ValueError:pass
 else:raise AssertionError('Preset ignored its file filter')
print('PASS: display label maps to legacy saved ID; exact 2/3/6 file filters; unsupported files excluded')
