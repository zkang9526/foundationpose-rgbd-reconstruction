#!/usr/bin/env python3
import json
import urllib.request

url = 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:wenbowen123/foundationpose:pull'
with urllib.request.urlopen(url, timeout=30) as response:
    token = json.load(response)['token']
request = urllib.request.Request(
    'https://registry-1.docker.io/v2/wenbowen123/foundationpose/manifests/latest',
    headers={'Authorization': 'Bearer ' + token,
             'Accept': 'application/vnd.docker.distribution.manifest.v2+json'},
)
with urllib.request.urlopen(request, timeout=30) as response:
    manifest = json.load(response)
print('Compressed image size: {:.2f} GiB'.format(sum(layer['size'] for layer in manifest['layers']) / 1024**3))
for layer in sorted(manifest['layers'], key=lambda x: x['size'], reverse=True)[:8]:
    print('{}: {:.2f} GiB'.format(layer['digest'][:24], layer['size'] / 1024**3))
