"""Bind one compiled neural CUDA module to upstream's import names."""
import importlib
import sys


def install_neural_cuda_aliases():
    """Call before importing run_nerf, Utils, or the official neural runner.

    Upstream loads the common extension through two package paths. Loading the
    same compiled binary repeatedly caused a native abort during process exit
    in this local PyTorch environment. Sharing one module preserves its kernels
    and allows ordinary interpreter cleanup.
    """
    try:
        common = importlib.import_module('common')
    except ModuleNotFoundError as error:
        if error.name != 'common':
            raise
        common = importlib.import_module('bundlesdf.mycuda.common')
    for name in ('postprocessOctreeRayTracing', 'sampleRaysUniformOccupiedVoxels'):
        if not hasattr(common, name):
            raise ValueError('Expected the compiled FoundationPose common extension')
    names = ('common', 'mycuda.common', 'bundlesdf.mycuda.common')
    for name in names:
        previous = sys.modules.get(name)
        if previous is not None and previous is not common:
            raise RuntimeError('Neural CUDA aliases must be installed before upstream imports')
        sys.modules[name] = common
    return dict(module_file=common.__file__, aliases=list(names), shared_module=True)
