#!/usr/bin/env python3
"""Resume isolated downloads via signed mirror; never modify host/original FP APT."""
import argparse
from deploy_bundlesdf_isolated_20261013 import docker, logged, PYTHON

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['interrupt_download', 'mirror', 'install', 'python'], required=True)
    args = parser.parse_args()
    if args.stage == 'interrupt_download':
        script = """import os,signal,json
targets=[]
for name in os.listdir('/proc'):
    if not name.isdigit(): continue
    try: argv=open('/proc/'+name+'/cmdline','rb').read().decode().split('\\0')
    except (OSError,UnicodeError): continue
    if argv[0].endswith('apt-get') and 'install' in argv and 'libpcl-dev' in argv: targets.append(int(name))
if len(targets)!=1: raise RuntimeError('Expected exactly our active apt download; found '+str(targets))
os.kill(targets[0],signal.SIGINT)
print(json.dumps({'interrupted_isolated_apt_pid':targets[0],'signal':'SIGINT','cached_packages_retained':True}))
"""
        logged('bundlesdf_interrupt_slow_download', docker(['python3', '-c', script]))
        return
    location = '/etc/apt/bundlesdf_tuna_20261013.list'
    options = ['-o', 'Dir::Etc::sourcelist='+location, '-o', 'Dir::Etc::sourceparts=-',
               '-o', 'APT::Get::List-Cleanup=0']
    if args.stage == 'mirror':
        script = """from pathlib import Path
p=Path('/etc/apt/bundlesdf_tuna_20261013.list')
if p.exists(): raise FileExistsError(str(p))
lines=['deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ '+suite+' main restricted universe multiverse' for suite in ['focal','focal-updates','focal-backports']]
lines.append('deb http://security.ubuntu.com/ubuntu/ focal-security main restricted universe multiverse')
p.write_text('\\n'.join(lines)+'\\n')
print(p.read_text())
"""
        logged('bundlesdf_isolated_mirror_file', docker(['python3', '-c', script]))
        logged('bundlesdf_isolated_mirror_update', docker(['apt-get']+options+['update']))
    elif args.stage == 'install':
        logged('bundlesdf_isolated_native_deps_mirror', docker(['env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get']+options+[
            'install', '-y', '--no-install-recommends', 'libpcl-dev', 'libopencv-dev', 'libeigen3-dev',
            'libyaml-cpp-dev', 'libzmq3-dev', 'freeglut3-dev', 'libblas-dev', 'liblapack-dev',
            'libboost-system-dev', 'libboost-program-options-dev', 'libboost-serialization-dev', 'libspdlog-dev']))
    else:
        logged('bundlesdf_isolated_python_deps', docker([PYTHON, '-m', 'pip', 'install', '--no-deps',
             'dearpygui==1.11.1', 'PyMCubes==0.1.4', 'gdown==5.2.0']))

if __name__ == '__main__':
    main()
