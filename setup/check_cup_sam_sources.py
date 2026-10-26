"""Parse modified Python and browser JavaScript; temporary file stays on E."""
import ast
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
names = ['cup_sam_mask.py', 'cup_sam_worker.py', 'run_cup_live_fast.py', 'run_cup_live_worker.py',
         'cup_live_dashboard.py', 'verify_cup_sam.py', 'cup_sam2_mask.py', 'cup_sam2_worker.py',
         'cup_reacquisition.py', 'sam2_runtime_environment.py', 'verify_cup_reacquisition.py']
for name in names:
    ast.parse((root / 'setup' / name).read_text(encoding='utf-8-sig'))
text = (root / 'setup/cup_live_dashboard.py').read_text(encoding='utf-8-sig')
js = text.split('<script>')[1].split('</script>')[0]
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', encoding='utf-8', delete=False) as handle:
    handle.write(js)
    path = pathlib.Path(handle.name)
subprocess.run(['node', '--check', str(path)], check=True)
print('Python AST and browser JavaScript syntax passed; retained JS:', path)
