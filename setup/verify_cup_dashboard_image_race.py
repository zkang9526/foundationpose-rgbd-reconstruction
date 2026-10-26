#!/usr/bin/env python3
"""Reproduce overlapping image-load/status polling race in actual dashboard JS."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from cup_live_dashboard import HTML

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--expect-stall',action='store_true')
args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
program=r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8')),pending=new Map(),elements=new Map();
const ctx=new Proxy({}, {get:()=>()=>{}});
function el(id){if(!elements.has(id))elements.set(id,{value:'box',disabled:false,hidden:false,textContent:'',getContext:()=>ctx});return elements.get(id)}
let current={output:'session-a',state:'waiting_for_roi',completed:0,failed:0,segmentation_backend:'SAM2',message:'ready'};
let rejectFetch=false;
class Image{constructor(){this.complete=false;this.naturalWidth=0}set src(value){this._src=value;pending.set(this,value)}get src(){return this._src}}
const sandbox=vm.createContext({document:{getElementById:el},Image,fetch:async(url,options)=>{
 if(rejectFetch)throw Error('simulated disconnected server');
 return {ok:true,json:async()=>options?.method==='POST'?{message:'control ok',candidate_id:'mask-a'}:current};
},setInterval:()=>{},setTimeout,clearTimeout,AbortController,Date,Math,console});
const tick=()=>new Promise(setImmediate);
function flush(){for(const image of [...pending.keys()]){pending.delete(image);image.complete=true;image.naturalWidth=640;image.onload?.()}}
(async()=>{
 vm.runInContext(input.script,sandbox);await tick();
 const frozen=vm.runInContext('freeze()',sandbox);await tick();flush();await frozen;await tick();
 const stalled=vm.runInContext('busy',sandbox);
 if(input.expectStall){assert.equal(stalled,true);console.log(JSON.stringify({passed:true,old_shared_image_handler_race_reproduced:true}));return}
 assert.equal(stalled,false,'Overlapping freeze image load must release status poll');
 current={...current,state:'tracking_estimate_unverified',message:'tracking',completed:12,pose:[[1,0,0,0],[0,1,0,0],[0,0,1,.5],[0,0,0,1]]};
 await vm.runInContext('refresh()',sandbox);await tick();
 assert.equal(vm.runInContext('busy',sandbox),false,'Status cannot await image completion');
 assert.match(el('s').textContent,/12/);assert.equal(el('o').hidden,false);
 assert.equal(vm.runInContext('frozen',sandbox),false,'Server tracking state must clear stale freeze');
 assert.equal(el('msg').textContent,'tracking');
 flush();el('o').onload?.();await tick();
 rejectFetch=true;await vm.runInContext('refresh()',sandbox);
 assert.match(el('connection').textContent,/连接|断|失败/);
 assert.equal(vm.runInContext('busy',sandbox),false);
 rejectFetch=false;current={...current,completed:18};await vm.runInContext('refresh()',sandbox);
 assert.match(el('s').textContent,/18/);assert.match(el('connection').textContent,/已连接/);
 flush();el('o').onload?.();await tick();
 vm.runInContext('frozen=true;rect=[1,2,3,4];maskId="old";points=[[2,3]];labels=[1]',sandbox);
 await vm.runInContext('act("/initialize",{candidate_id:maskId})',sandbox);
 assert.equal(vm.runInContext('rect',sandbox),null);assert.equal(el('initButton').disabled,true);
 flush();el('o').onload?.();await tick();
 console.log(JSON.stringify({passed:true,overlapping_image_requests_do_not_block_status:true,status_updates_without_image_completion:true,server_tracking_unfreezes_ui:true,network_failure_visible_and_recovers:true,initialize_clears_old_mask_controls:true}));
})().catch(error=>{console.error(error);process.exitCode=1});
'''
result=subprocess.run(['node','-e',program],input=json.dumps(dict(script=HTML.split('<script>',1)[1].split('</script>',1)[0],expectStall=args.expect_stall)),text=True,capture_output=True)
report=dict(passed=result.returncode==0,html_sha256=hashlib.sha256(HTML.encode()).hexdigest(),stdout=result.stdout,stderr=result.stderr,
            scope='Actual dashboard JS with controlled slow image/network events; no pose accuracy claim')
(args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
raise SystemExit(result.returncode)
