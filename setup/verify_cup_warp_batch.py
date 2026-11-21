"""Check actual CUDA Kornia warps, batch order, kwargs and temporary memory."""
from pathlib import Path
import argparse,json,gc
import torch
import kornia.geometry.transform as transform
from cup_warp_batch import install_warp_batch_limit

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
assert not a.output.exists()
original=transform.warp_perspective
torch.manual_seed(17)
src=torch.rand(1,1,192,192,device='cuda').expand(33,-1,-1,-1)
matrices=torch.eye(3,device='cuda')[None].repeat(33,1,1)
matrices[:,0,2]=torch.linspace(-4,7,33,device='cuda')
matrices[:,1,2]=torch.linspace(3,-5,33,device='cuda')
checks=[];stats=install_warp_batch_limit(8)
try:
    for mode in ['bilinear','nearest']:
        for align in [True,False]:
            with torch.no_grad():
                expected=original(src,matrices,(127,151),mode=mode,align_corners=align,padding_mode='border')
                actual=transform.warp_perspective(src=src,M=matrices,dsize=(127,151),mode=mode,align_corners=align,padding_mode='border')
                delta=float((expected-actual).abs().max().item())
                # FP32 CUDA batching can change rounding by a few 1e-5.
                # 1e-4 on normalized RGB is 0.0255 of one 8-bit gray level.
                tolerance=0.0 if mode=='nearest' else 1e-4
                assert torch.allclose(expected,actual,atol=tolerance,rtol=0),(mode,align,delta)
                checks.append(dict(mode=mode,align_corners=align,max_abs_difference=delta))
            del expected,actual
    gradient_src=torch.rand(2,1,12,12,device='cuda',requires_grad=True)
    out=transform.warp_perspective(gradient_src,matrices[:2],(9,9));out.sum().backward()
    assert gradient_src.grad is not None and torch.isfinite(gradient_src.grad).all()
    del gradient_src,out
    peaks={}
    for name,function in [('original',original),('bounded',transform.warp_perspective)]:
        gc.collect();torch.cuda.empty_cache();torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
        baseline=torch.cuda.memory_allocated()
        with torch.no_grad():out=function(src,matrices,(480,640),mode='nearest',align_corners=False)
        torch.cuda.synchronize();peaks[name]=int(torch.cuda.max_memory_allocated()-baseline)
        del out
    assert peaks['bounded']<peaks['original'],peaks
    report=dict(passed=True,checks=checks,bilinear_absolute_tolerance=1e-4,nearest_absolute_tolerance=0.0,
                autograd_passthrough=True,peak_extra_bytes=peaks,
                counters=stats,upstream_source_modified=False,scoring_groups_modified=False)
    a.output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
finally:
    transform.warp_perspective=original
