import importlib.util,sys,runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cleanapp',root/'SC_CGF_Converter.py');m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
with patch('runpy.run_path') as call:
 runpy.run_path.__module__ # keep patch handle separate from actual driver
 code=(root/'SC_CGF_Converter.pyw').read_text()
 exec(compile(code,str(root/'SC_CGF_Converter.pyw'),'exec'),{'__name__':'__main__','__file__':str(root/'SC_CGF_Converter.pyw')})
 call.assert_called_once_with(str((root/'SC_CGF_Converter.py').resolve()),run_name='__main__')
class V:
 def __init__(self,value='',**kw):self.value=value
 def get(self):return self.value
 def set(self,v):self.value=v
class W:
 all=[]
 def __init__(self,*a,**kw):self.kw=kw;self.visible=False;self.bindings={};W.all.append(self)
 def __getattr__(self,n):
  if n in ['grid','pack']:return lambda *a,**k:setattr(self,'visible',True)
  if n in ['grid_remove','pack_forget']:return lambda *a,**k:setattr(self,'visible',False)
  if n=='bind':return lambda ev,cb,**kw:self.bindings.update({ev:cb})
  return lambda *a,**kw:None
 def __setitem__(self,k,v):self.kw[k]=v
 def __getitem__(self,k):return self.kw[k]
class H:
 def __getattr__(self,name):return lambda *a,**kw:None
for name in ['make_vars','button','build_ui','path_row','toggle_diagnostics']:
 setattr(H,name,getattr(m.App,name))
m.tk=SimpleNamespace(StringVar=V,BooleanVar=V,DoubleVar=V,Text=W,Toplevel=W)
m.ttk=SimpleNamespace(**{x:W for x in ['Frame','LabelFrame','Label','Button','Entry','Combobox','Checkbutton','Scrollbar','Progressbar']})
h=H();h.make_vars();h.build_ui()
assert h.var_batch.get() and h.var_preserve_folders.get() and not h.var_diagnostics.get()
assert any(w.kw.get('text')=='Input Folder' and w.visible for w in W.all)
assert any(w.kw.get('text')=='Help' and w.visible for w in W.all)
assert all(not w.visible for w in h.advanced_widgets)
buttons=[w for w in W.all if w.kw.get('text') in ['Help','Browse','Check Converter','Input Folder','File','Folder','EXPORT','Open Output','Collect Existing Outputs','Create Desktop Shortcut','Export Animation Only']]
assert buttons and all('<Enter>' in w.bindings for w in buttons)
h.var_diagnostics.set(True);h.toggle_diagnostics(refresh=False);assert all(w.visible for w in h.advanced_widgets)
h.var_diagnostics.set(False);h.toggle_diagnostics(refresh=False);assert all(not w.visible for w in h.advanced_widgets)
# Real command construction: CHR/CGA animation, SKIN/CGF geometry.
preset=m.read_json(root/'Presets/SC_Normal_Batch_USDA.json')
f=SimpleNamespace(var_converter=V('converter'),var_input=V(''),var_format=V('Preset'),var_objectdir=V(''),var_output=V(''),var_extra=V(''),current_preset=lambda:preset,native_output_dir_supported=lambda:False)
for ext in ['.chr','.cga','.skin','.cgf']:
 cmd=m.App.build_command(f,'asset'+ext)
 assert ('-anim' in cmd)==(ext in {'.chr','.cga'})
 assert '-usda' in cmd and 'debug' not in cmd
print('PASS: windowed launcher targets canonical code; clean UI folder button, hidden diagnostics, toggling, hover help, defaults and per-format batch commands')
