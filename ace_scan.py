import os, sys, json, subprocess, hashlib
from concurrent.futures import ThreadPoolExecutor
"""Run Ace by DAISY on every EPUB in a library.  Usage: ace_scan.py LIBRARY_DIR
Reports: work/<library>/ace/<hash>/report.html ; index + summary printed at the end."""
LIB = os.path.abspath(os.path.expanduser(sys.argv[1]))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work', os.path.basename(LIB.rstrip('/')), 'ace')
os.makedirs(OUT, exist_ok=True)
books = sorted(os.path.join(dp, f) for dp, dn, fn in os.walk(LIB) for f in fn if f.endswith('.epub'))
def one(p):
    d = os.path.join(OUT, hashlib.md5(p.encode()).hexdigest()[:12])
    if os.path.exists(os.path.join(d, 'report.json')):
        return dict(p=os.path.relpath(p, LIB), dir=d, ok=True, err='')
    try:
        r = subprocess.run(['ace', '-s', '-f', '-o', d, p], capture_output=True, text=True, timeout=7200)
        err = (r.stdout + r.stderr)[-500:]
    except subprocess.TimeoutExpired:
        err = 'timeout after 2h'
    ok = os.path.exists(os.path.join(d, 'report.json'))
    print(len(os.listdir(OUT)), 'ok' if ok else 'FAIL', os.path.basename(p), flush=True)
    return dict(p=os.path.relpath(p, LIB), dir=d, ok=ok, err='' if ok else err)
with ThreadPoolExecutor(3) as ex:
    R = list(ex.map(one, books))
for r in R:  # one retry, alone, for any failure
    if not r['ok']:
        r.update(one(os.path.join(LIB, r['p'])))
json.dump(R, open(OUT + '_index.json', 'w'), indent=0)
print('done', sum(r['ok'] for r in R), 'of', len(R))
import collections
rules, books_hit = collections.Counter(), collections.Counter()
for r in R:
    if not r['ok']: continue
    seen = set()
    for a in json.load(open(os.path.join(r['dir'], 'report.json')))['assertions']:
        for x in a['assertions']:
            k = (x['earl:test']['earl:impact'], x['earl:test']['dct:title']); rules[k] += 1; seen.add(k)
    for k in seen: books_hit[k] += 1
print('books with no Ace findings:', sum(1 for r in R if r['ok']) - len({r['p'] for r in R if r['ok'] and json.load(open(os.path.join(r['dir'], 'report.json')))['assertions']}))
for k, v in sorted(books_hit.items(), key=lambda kv: -kv[1]):
    print('%4d books %7d hits  %-9s %s' % (v, rules[k], k[0], k[1]))
