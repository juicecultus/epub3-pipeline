#!/usr/bin/env python3
"""Headless ePub3-itizer: run Sigil's plugin launcher on one EPUB2 -> EPUB3."""
import os, re, sys, zipfile, tempfile, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixes
HERE = os.path.dirname(os.path.abspath(__file__))
SIGIL = '/Applications/Sigil.app/Contents'
PY = SIGIL + '/Frameworks/Python.framework/Versions/3.14/bin/python3'
LAUNCHER = SIGIL + '/plugin_launchers/python/launcher.py'
PLUGIN = HERE + '/plugins/ePub3-itizer/plugin.py'

def convert(src, out):
    tmp = tempfile.mkdtemp(prefix='e3_')
    try:
        root, outdir = os.path.join(tmp, 'book'), os.path.join(tmp, 'out')
        os.makedirs(outdir)
        with zipfile.ZipFile(src) as z:
            z.extractall(root)
        c = open(os.path.join(root, 'META-INF/container.xml'), encoding='utf-8', errors='ignore').read()
        opf = re.search(r'full-path="([^"]+)"', c).group(1)
        fixes.pre(root, opf)
        cfg = [opf, SIGIL + '/MacOS', HERE + '/usr', 'en', 'en_US', 'False', os.path.abspath(src),
               'light', '', '', '', '', '', '']
        open(os.path.join(outdir, 'sigil.cfg'), 'w', encoding='utf-8').write('\n'.join(cfg))
        env = dict(os.environ, PYTHONPATH=HERE + '/stubs', EPUB3_OUT=os.path.abspath(out))
        r = subprocess.run([PY, LAUNCHER, root, outdir, 'output', PLUGIN],
                           capture_output=True, text=True, env=env, timeout=900)
        log = r.stdout + r.stderr
        ok = 'Output Conversion Complete' in log and os.path.exists(out)
        if ok:
            fixes.post(out)
        return ok, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__':
    ok, log = convert(sys.argv[1], sys.argv[2])
    if not ok: print(log[-3000:])
    print('OK' if ok else 'FAILED')
