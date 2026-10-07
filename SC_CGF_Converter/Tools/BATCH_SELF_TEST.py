import importlib.util,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('batchapp',root/'SC_CGF_Converter.py');m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
class V:
 def __init__(self,x):self.x=x
 def get(self):return self.x
with tempfile.TemporaryDirectory(dir='.') as t:
 base=Path(t).resolve();source=base/'Input';out=source/'Output';out.mkdir(parents=True)
 for name in ['root.chr','Ships/Anvil/gear.chr','Ships/Aegis/gear.chr','Output/old.chr','OutputBackup/keep.skin','notes.txt']:
  p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
 jobs=m.plan_batch_jobs(source,out)
 assert len(jobs)==4
 assert dict(jobs)[source/'root.chr']==out
 assert dict(jobs)[source/'Ships/Anvil/gear.chr']==out/'Ships/Anvil'
 assert source/'OutputBackup/keep.skin' in dict(jobs)
 assert len(m.plan_batch_jobs(source,out,False))==1
 try:m.plan_batch_jobs(source,out,True,False)
 except ValueError as e:assert 'collision' in str(e)
 else:raise AssertionError('Flat duplicate accepted')
 try:m.plan_batch_jobs(source,source)
 except ValueError:pass
 else:raise AssertionError('Same output accepted')
 for name in ['A/a.dba','B/b.dba']:
  p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
 assert len(m.plan_batch_jobs(source,out,dba_only=True))==2
 fake=SimpleNamespace(var_converter=V('converter'),var_input=V('unused'),var_format=V('USDA'),var_objectdir=V(str(source)),var_output=V('unused'),var_extra=V(''),current_preset=lambda:{'converter_args':['-usda']},native_output_dir_supported=lambda:True,converter_usage_text='-outdir')
 cmd=m.App.build_command(fake,source/'root.chr',out)
 assert cmd[1]==str(source/'root.chr') and cmd[cmd.index('-outdir')+1]==str(out)
 fake.native_output_dir_supported=lambda:False
 assert '-outdir' not in m.App.build_command(fake,source/'root.chr',out)
 # Run actual collection method into planned nested output; do not flatten.
 asset=source/'Ships/Anvil/gear.chr';export=asset.with_suffix('.usda');export.write_text('sample')
 fake.var_collect_outputs=V(True);fake.expected_export_extensions=lambda _: {'.usda'};fake.post_log=lambda _:None
 result=m.App.collect_native_exports(fake,str(asset),['converter','-usda'],{},out/'Ships/Anvil')
 assert result==[str(out/'Ships/Anvil/gear.usda')]
 assert (out/'Ships/Anvil/gear.usda').read_text()=='sample'
 assert not (out/'gear.usda').exists()
print('PASS: recursive scan, root/nested mapping, output pruning, sibling prefix, nonrecursive mode, flat collision, DBA-only scan, native command and fallback collection')
