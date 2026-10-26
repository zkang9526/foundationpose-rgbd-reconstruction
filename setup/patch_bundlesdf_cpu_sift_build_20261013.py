#!/usr/bin/env python3
"""Use existing CPU legacy SIFT branch; active LoFTR/CUDA RANSAC unchanged."""
from pathlib import Path
import subprocess
from deploy_bundlesdf_isolated_20261013 import CODE, AUDIT

cmake = CODE / 'BundleTrack/CMakeLists.txt'
text = cmake.read_text().replace('c++17', 'c++14').replace('-DCUDA_MATCHING=1', '-DCUDA_MATCHING=0')
cmake.write_text(text)
utils = CODE / 'BundleTrack/src/Utils.cpp'
text = utils.read_text()
for include in ['#include <opencv2/cudaimgproc.hpp>', '#include <opencv2/cudaoptflow.hpp>']:
    if include not in text:
        raise RuntimeError('Expected original include absent: ' + include)
    text = text.replace(include, '// Unused CUDA OpenCV include omitted for packaged OpenCV4.')
utils.write_text(text)
feature = CODE / 'BundleTrack/src/FeatureManager.cpp'
text = feature.read_text().replace('#include <opencv2/cudafeatures2d.hpp>',
    '// Legacy SIFT uses CPU matching; active LoFTR/CUDA RANSAC unchanged.')
signature = 'void SiftManager::findCorresbyNNMultiPair(std::vector<FramePair> &pairs)'
start = text.index(signature)
opening = text.index('{', start)
balance = 1
index = opening + 1
while balance:
    if text[index] == '{': balance += 1
    elif text[index] == '}': balance -= 1
    index += 1
original = text[opening:index]
# Preserve exact original helper in an archival file, not compiled.
archive = AUDIT / 'legacy_gpu_sift_multipair_original.cpp.txt'
if archive.exists():
    raise FileExistsError(str(archive))
archive.write_text(signature+'\n'+original+'\n')
replacement = '''{
  // Compatibility fallback for optional legacy SIFT. GluNet overrides this
  // virtual method and remains the active LoFTR matcher used by BundleSDF.
  for (const auto &pair : pairs)
  {
    findCorresbyNN(pair.first, pair.second);
  }
}'''
feature.write_text(text[:opening]+replacement+text[index:])
diff = subprocess.run(['git', '-C', str(CODE), 'diff'], capture_output=True, text=True, check=True)
evidence = AUDIT / 'deployment_adaptations_v3.diff'
if evidence.exists():
    raise FileExistsError(str(evidence))
evidence.write_text(diff.stdout)
print(diff.stdout)
