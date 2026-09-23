import subprocess, json, tempfile, os, collections
def check(path):
    fd, j = tempfile.mkstemp(suffix='.json'); os.close(fd)
    subprocess.run(['epubcheck', path, '--json', j], capture_output=True, timeout=900)
    try: d = json.load(open(j))
    except Exception: return {'FATAL': 1}, [], None
    finally: os.remove(j)
    c = collections.Counter(m['severity'] for m in d['messages'])
    return dict(c), d['messages'], d.get('publication', {}).get('ePubVersion')
