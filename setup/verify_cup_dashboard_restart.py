#!/usr/bin/env python3
"""Exercise actual dashboard JS across session changes using Node and a simulated DOM."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from cup_live_dashboard import HTML

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
script = HTML.split('<script>', 1)[1].split('</script>', 1)[0]
program = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const script=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),ctx=new Proxy({}, {get:()=>()=>{}});
function el(id){if(!elements.has(id))elements.set(id,{value:'box',disabled:false,hidden:false,getContext:()=>ctx});return elements.get(id)}
let status={output:'session-a',state:'waiting_for_roi',completed:0,failed:0,segmentation_backend:'SAM ViT-B',message:'old loading text'};
class Image{constructor(){this.complete=false;this.naturalWidth=0}set src(v){this.complete=true;this.naturalWidth=640;queueMicrotask(()=>this.onload?.())}}
const sandbox=vm.createContext({document:{getElementById:el},Image,fetch:async()=>({json:async()=>status}),setInterval:()=>{},setTimeout,clearTimeout,AbortController,Date,Math});
(async()=>{
vm.runInContext(script,sandbox);
await new Promise(setImmediate);
assert.match(el('msg').textContent,/已就绪/);
vm.runInContext('frozen=true;drag=true;start=[1,2];rect=[1,2,3,4];points=[[2,3]];labels=[1];maskId="old-mask";document.getElementById("initButton").disabled=false;document.getElementById("mode").value="1"',sandbox);
status={...status,output:'session-b'};
await vm.runInContext('refresh()',sandbox);
assert.equal(vm.runInContext('frozen',sandbox),false);
assert.equal(vm.runInContext('drag',sandbox),false);
assert.equal(vm.runInContext('rect',sandbox),null);
assert.equal(vm.runInContext('maskId',sandbox),null);
assert.equal(vm.runInContext('points.length+labels.length',sandbox),0);
assert.equal(el('initButton').disabled,true);
assert.equal(el('mode').value,'box');
vm.runInContext('frozen=true;rect=[10,20,30,40];points=[[12,23]];labels=[1]',sandbox);
await vm.runInContext('refresh()',sandbox);
assert.equal(vm.runInContext('frozen',sandbox),true);
assert.equal(vm.runInContext('rect[0]',sandbox),10);
assert.equal(vm.runInContext('points.length',sandbox),1);
process.stdout.write(JSON.stringify({passed:true,new_session_resets_old_freeze_roi_prompts_and_mask:true,same_session_preserves_manual_selection:true,waiting_prompt_ready:true}));
})().catch(error=>{process.stderr.write(String(error));process.exitCode=1});
'''
result = subprocess.run(['node', '-e', program], input=json.dumps(script), text=True, capture_output=True, check=True)
report = json.loads(result.stdout)
report.update(scope='actual JavaScript with simulated DOM; no camera/GPU interruption',
              html_sha256=hashlib.sha256(HTML.encode()).hexdigest())
ast.parse((Path(__file__).parent / 'run_cup_live_fast.py').read_text(encoding='utf-8-sig'))
(args.output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report))
