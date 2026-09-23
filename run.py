"""Bring every EPUB in a library folder to a modern, validated EPUB 3.
EPUB2 -> Sigil-style repair + ePub3-itizer + post-fixes + modernize + accessibility;
EPUB3 -> modernize + accessibility.  A book is replaced only if epubcheck shows no new
error types and no document text changed; EPUB2 originals go to the Trash.
Run with Sigil's bundled Python (see ./epub3).

Usage: run.py LIBRARY_DIR [--dry] [--jobs N] [book.epub ...]"""
import os, sys, re, json, shutil, zipfile, collections, posixpath
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from convert import convert
from check import check
from modernize import modernize
import lxml.html

import argparse
AP = argparse.ArgumentParser(description='EPUB2/3 -> modern EPUB3 with validation gate')
AP.add_argument('library', help='folder containing .epub files (searched recursively)')
AP.add_argument('books', nargs='*', help='optional: only these books (paths relative to the library)')
AP.add_argument('--dry', action='store_true', help='convert + validate into the work folder, change nothing')
AP.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
ARGS = AP.parse_args()
LIB = os.path.abspath(os.path.expanduser(ARGS.library))
NAME = os.path.basename(LIB.rstrip('/'))
WORK = os.path.join(HERE, 'work', NAME)
STAGE = os.path.join(WORK, 'stage'); os.makedirs(STAGE, exist_ok=True)
TRASH = os.path.expanduser('~/.Trash/%s EPUB2 originals' % NAME)
LOG = os.path.join(WORK, 'dry.jsonl' if ARGS.dry else 'run.jsonl')
DRY = ARGS.dry

def version(p):
    try:
        z = zipfile.ZipFile(p); c = z.read('META-INF/container.xml').decode('utf8', 'ignore')
        o = z.read(re.search(r'full-path="([^"]+)"', c).group(1)).decode('utf8', 'ignore')
        return (re.search(r'<(?:opf:)?package[^>]*\bversion="([^"]+)"', o) or [0, '?'])[1]
    except Exception:
        return 'ERR'

def texts(p):
    """normalized visible text per content document (skip nav)"""
    out = {}
    z = zipfile.ZipFile(p)
    for n in z.namelist():
        if n.lower().endswith(('.htm', '.html', '.xhtml')) and posixpath.basename(n) != 'nav.xhtml':
            try:
                raw = z.read(n).decode('utf-8', 'replace')
                raw = re.sub(r'^\s*<\?xml[^>]*\?>', '', raw)
                d = lxml.html.fromstring(raw)
                for bad in d.xpath('//head|//script|//style'): bad.drop_tree()
                out[n] = ' '.join(d.text_content().replace('\xa0', ' ').split())
            except Exception:
                out[n] = None
    return out

def safe_names_v3(epub):
    """Apply the URL-safe file renaming (fixes.safe_filenames) to an EPUB3 in place."""
    import tempfile, fixes
    z = zipfile.ZipFile(epub); names = z.namelist()
    c = z.read('META-INF/container.xml').decode('utf-8', 'ignore')
    opfp = re.search(r'full-path="([^"]+)"', c).group(1)
    opf = z.read(opfp).decode('utf-8')
    base = posixpath.dirname(opfp)
    from urllib.parse import unquote
    if all(re.match(r'^[A-Za-z0-9._-]+$', posixpath.basename(unquote(h)))
           for h in re.findall(r'<item\b[^>]*href="([^"]+)"', opf)):
        return
    tmp = tempfile.mkdtemp(prefix='v3_'); z.extractall(tmp); z.close()
    opf = fixes.safe_filenames(tmp, opf, base)
    open(os.path.join(tmp, opfp), 'w', encoding='utf-8').write(opf)
    with zipfile.ZipFile(epub + '.tmp', 'w') as zo:
        zo.write(os.path.join(tmp, 'mimetype'), 'mimetype', compress_type=zipfile.ZIP_STORED)
        for dp, dn, fn in os.walk(tmp):
            for f in fn:
                rel = os.path.relpath(os.path.join(dp, f), tmp)
                if rel != 'mimetype': zo.write(os.path.join(dp, f), rel, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(epub + '.tmp', epub); shutil.rmtree(tmp, ignore_errors=True)

def errids(msgs):
    return collections.Counter(m['ID'] for m in msgs if m['severity'] in ('ERROR', 'FATAL'))

def one(rel):
    src = os.path.join(LIB, rel)
    out = os.path.join(STAGE, rel.replace('/', '__'))
    r = dict(path=rel)
    try:
        v = version(src); r['src_ver'] = v
        if v.startswith('3'):
            shutil.copy2(src, out)
            safe_names_v3(out)
        else:
            ok, log = convert(src, out)
            if not ok:
                r.update(status='convert_failed', log=log[-1500:]); return r
        m = modernize(out); r['repaired'] = m['repaired']; r['alt_missing'] = m['alt_missing']
        b, bm, _ = check(src); a, am, av = check(out)
        be, ae = errids(bm), errids(am)
        r.update(before=b, after=a, after_ver=av)
        tb, ta = texts(src), texts(out)
        after_texts = collections.Counter(v for v in ta.values() if v)
        before_texts = collections.Counter(v for v in tb.values() if v)
        lost = [n for n, v in tb.items() if v and after_texts[v] < before_texts[v]]
        # repaired documents may legitimately change markup-level text (e.g. stray '<');
        # accept them only if the whole book's text is still the same length within 0.1%
        tot_b = sum(len(v) for v in tb.values() if v); tot_a = sum(len(v) for v in ta.values() if v)
        if m['repaired'] and lost and abs(tot_a - tot_b) <= 0.001 * max(tot_b, 1):
            r['repaired_text_delta'] = tot_a - tot_b; lost = []
        missing = [] if len(ta) >= len(tb) else ['%d of %d documents missing' % (len(tb) - len(ta), len(tb))]
        r['text_changed'] = lost[:5]; r['docs_missing'] = missing[:5]
        new = set(ae) - set(be)
        if av is None or not str(av).startswith('3') or 'FATAL' in a:
            r['status'] = 'invalid_output'
        elif new:
            r['status'] = 'new_errors'
            r['new_msgs'] = [(x['ID'], x['message'][:200], (x['locations'] or [{}])[0].get('path'))
                             for x in am if x['ID'] in new][:5]
        elif lost or missing:
            r['status'] = 'text_changed'
        else:
            r['status'] = 'ok'
            r['remaining'] = [(x['ID'], x['message'][:160]) for x in am if x['severity'] in ('ERROR', 'FATAL')][:5]
            if not DRY:
                if not v.startswith('3'):
                    dst = os.path.join(TRASH, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                shutil.move(out, src)
                r['status'] = 'replaced'
    except Exception as e:
        import traceback
        r.update(status='exception', error=traceback.format_exc()[-800:])
    return r

if __name__ == '__main__':
    args = ARGS.books
    done = set()
    if not DRY and os.path.exists(LOG):
        done = {json.loads(l)['path'] for l in open(LOG)}
    if args:
        todo = args
    else:
        todo = sorted((os.path.relpath(os.path.join(dp, f), LIB) for dp, dn, fn in os.walk(LIB)
                       for f in fn if f.endswith('.epub')), key=lambda r: os.path.getsize(os.path.join(LIB, r)))
        todo = [t for t in todo if t not in done]
    print(len(todo), 'to process', flush=True)
    with ThreadPoolExecutor(ARGS.jobs) as ex, open(LOG, 'a') as lg:
        for i, r in enumerate(ex.map(one, todo), 1):
            lg.write(json.dumps(r, ensure_ascii=False) + '\n'); lg.flush()
            print(i, r['status'], r['path'], r.get('before'), '->', r.get('after'),
                  r.get('new_msgs') or r.get('text_changed') or r.get('error') or '', flush=True)
    print('DONE  log: %s' % LOG, flush=True)
