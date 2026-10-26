#!/usr/bin/env python3
"""Remove unused nonfree header for packaged OpenCV4; save patch separately."""
import subprocess
from deploy_bundlesdf_isolated_20261013 import CODE, AUDIT

header = CODE / 'BundleTrack/src/FeatureManager.h'
source = CODE / 'BundleTrack/src/FeatureManager.cpp'
uses = [line for line in source.read_text().splitlines() if 'xfeatures2d' in line and not line.lstrip().startswith('//')]
if uses:
    raise RuntimeError('Active nonfree use; cannot remove include: ' + str(uses))
text = header.read_text()
marker = '#include <opencv2/xfeatures2d/nonfree.hpp>'
if marker not in text:
    raise RuntimeError('Expected original nonfree include missing')
header.write_text(text.replace(marker, '// Unused nonfree header removed for Ubuntu OpenCV4 package.'))
diff = subprocess.run(['git', '-C', str(CODE), 'diff'], capture_output=True, text=True, check=True)
evidence = AUDIT / 'deployment_adaptations_v2.diff'
if evidence.exists():
    raise FileExistsError(str(evidence))
evidence.write_text(diff.stdout)
print(diff.stdout)
