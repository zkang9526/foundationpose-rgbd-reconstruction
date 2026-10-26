"""Parallel ranged official wheel download with index SHA, retained resumable parts."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import urllib.parse
import urllib.request
import time
import sys

checkpoint_mode = '--checkpoint' in sys.argv
folder = Path('/data/ZJC/foundationPos/foundationpose_data/cache/' + ('sam2_checkpoint_parts' if checkpoint_mode else 'sam2_wheels'))
folder.mkdir(parents=True, exist_ok=True)
filename = 'torch-2.5.1+cu121-cp311-cp311-linux_x86_64.whl'
if checkpoint_mode:
    filename = 'sam2.1_hiera_tiny.pt'

class Links(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if urllib.parse.unquote(urllib.parse.urlparse(href).path).endswith('/' + filename):
                self.href = href

if checkpoint_mode:
    url = 'https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt'
    expected_sha = None
else:
    parser = Links()
    with urllib.request.urlopen('https://download.pytorch.org/whl/cu121/torch/', timeout=60) as r:
        parser.feed(r.read().decode())
    url, fragment = urllib.parse.urldefrag(parser.href)
    expected_sha = urllib.parse.parse_qs(fragment)['sha256'][0]
req = urllib.request.Request(url, headers={'Range': 'bytes=0-0'})
with urllib.request.urlopen(req, timeout=60) as r:
    if r.status != 206 or not r.headers.get('Content-Range', '').startswith('bytes 0-0/'):
        raise RuntimeError('Official server does not honor byte ranges')
    total = int(r.headers['Content-Range'].split('/')[-1])
parts = 16 if checkpoint_mode else 8

def download(index):
    start, end = total * index // parts, total * (index+1) // parts - 1
    path = folder / (filename + '.part' + str(index))
    if path.exists() and path.stat().st_size == end-start+1:
        return path
    for attempt in range(25):
        existing = path.stat().st_size if path.exists() else 0
        if existing == end-start+1:
            break
        req = urllib.request.Request(url + '?range_part=%d&attempt=%d&offset=%d' % (index, attempt, existing),
                                     headers={'Range': 'bytes=%d-%d' % (start+existing, end)})
        began, received = time.monotonic(), 0
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 206 or r.headers.get('Content-Range') != 'bytes %d-%d/%d' % (start+existing, end, total):
                    raise RuntimeError('Range response mismatch')
                with path.open('ab') as stream:
                    while True:
                        block = r.read(256 * 1024)
                        if not block:
                            break
                        stream.write(block)
                        received += len(block)
                        elapsed = time.monotonic() - began
                        if elapsed > 20 and received / elapsed < 512 * 1024:
                            break  # Resume slow CDN responses without losing verified offsets.
        except (TimeoutError, OSError):
            continue
    assert path.stat().st_size == end-start+1
    print('Verified length for official wheel part', index, flush=True)
    return path

with ThreadPoolExecutor(max_workers=8) as pool:
    paths = list(pool.map(download, range(parts)))
target = Path('/data/ZJC/foundationPos/foundationpose_data/checkpoints/sam2') / filename if checkpoint_mode else folder / filename
target.parent.mkdir(parents=True, exist_ok=True)
with target.open('xb') as dest:
    for path in paths:
        with path.open('rb') as source:
            for block in iter(lambda: source.read(4*1024**2), b''):
                dest.write(block)
h = hashlib.sha256()
with target.open('rb') as source:
    for block in iter(lambda: source.read(4*1024**2), b''):
        h.update(block)
if expected_sha is not None:
    assert h.hexdigest() == expected_sha
print('SHA256:', h.hexdigest(), '; author index SHA verified:', expected_sha is not None, '; file:', target, flush=True)
