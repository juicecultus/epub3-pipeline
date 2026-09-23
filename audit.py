import os, sys, json, zipfile, re, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check import check
"""epubcheck audit of every EPUB in a library.  Usage: audit.py LIBRARY_DIR"""
LIB = os.path.abspath(os.path.expanduser(sys.argv[1]))
books = sorted(os.path.join(dp, f) for dp, dn, fn in os.walk(LIB) for f in fn if f.endswith('.epub'))
def one(p):
    c, m, v = check(p)
    z = zipfile.ZipFile(p); cx = z.read('META-INF/container.xml').decode()
    opf = z.read(re.search(r'full-path="([^"]+)"', cx).group(1)).decode('utf-8', 'replace')
    return dict(p=os.path.relpath(p, LIB), ver=v, counts=c,
                a11y=all(k in opf for k in ('schema:accessMode"', 'schema:accessModeSufficient', 'schema:accessibilityFeature', 'schema:accessibilityHazard', 'schema:accessibilitySummary')),
                nav='properties="nav"' in opf or "properties=\"nav " in opf,
                cover='cover-image' in opf,
                msgs=[(x['severity'], x['ID'], x['message'][:120]) for x in m if x['severity'] in ('ERROR', 'FATAL', 'WARNING')])
with ThreadPoolExecutor(4) as ex:
    R = list(ex.map(one, books))
W = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work', os.path.basename(LIB.rstrip('/')))
os.makedirs(W, exist_ok=True)
json.dump(R, open(os.path.join(W, 'audit.json'), 'w'), indent=0)
print('books', len(R))
print('versions', collections.Counter(r['ver'] for r in R))
print('zero errors', sum(1 for r in R if not any(k in r['counts'] for k in ('ERROR', 'FATAL'))))
print('zero errors+warnings', sum(1 for r in R if not any(k in r['counts'] for k in ('ERROR', 'FATAL', 'WARNING'))))
print('a11y metadata', sum(r['a11y'] for r in R), ' nav', sum(r['nav'] for r in R), ' cover-image', sum(r['cover'] for r in R))
w = collections.Counter((s, i, m[:90]) for r in R for s, i, m in r['msgs'])
for k, v in w.most_common(12): print(v, k)
for r in R:
    if not r['cover'] or any(k in r['counts'] for k in ('ERROR', 'FATAL')): print('  ', r['p'][:80], r['counts'], 'cover' if r['cover'] else 'NO COVER')
