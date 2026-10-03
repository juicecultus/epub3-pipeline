"""Book-wide EPUB3 hygiene run at the end of modernize(): structure the HTML
content model, valid ids with link remapping, dangling links/resources,
guide/spine/NCX consistency.  Operates on the in-memory {zip name: bytes} map."""
import re, posixpath
from urllib.parse import unquote, quote
from lxml import etree

XHTML = 'http://www.w3.org/1999/xhtml'
H = lambda t: '{%s}%s' % (XHTML, t)
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)

HTML5 = set('''a abbr address area article aside audio b base bdi bdo blockquote body br button canvas
caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset
figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd
label legend li link main map mark math menu meta meter nav noscript object ol optgroup option output p
param picture pre progress q rp rt ruby s samp script search section select slot small source span
strong style sub summary sup svg table tbody td template textarea tfoot th thead time title tr track u
ul var video wbr'''.split())
BLOCK = set('address article aside blockquote details dialog div dl fieldset figure footer form h1 h2 h3 '
            'h4 h5 h6 header hgroup hr main menu nav ol p pre section table ul'.split())
PHRASING_PARENT = set('p span b i em strong small sub sup u s cite q abbr code label dfn kbd samp var '
                      'mark bdi bdo time data ins del'.split())
HEADINGISH = set('h1 h2 h3 h4 h5 h6 pre dt caption legend summary'.split())
DEPRECATED_ROLES = {'doc-footnotes', 'doc-endnote', 'doc-biblioentry'}
XMLNAME = re.compile(r'^[^\W\d.\-][\w.\-]*$', re.U)

def _local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else None

def _style(el, decl):
    cur = (el.get('style') or '').strip().rstrip(';')
    el.set('style', (cur + '; ' if cur else '') + decl)

def _unwrap(el):
    par = el.getparent()
    if par is None: return
    idx = par.index(el)
    prev = el.getprevious()
    if el.text:
        if prev is not None: prev.tail = (prev.tail or '') + el.text
        else: par.text = (par.text or '') + el.text
    kids = list(el)
    for i, k in enumerate(kids): par.insert(idx + i, k)
    last = kids[-1] if kids else el.getprevious()
    if el.tail:
        if last is not None and last is not el: last.tail = (last.tail or '') + el.tail
        else: par.text = (par.text or '') + el.tail
    par.remove(el)

def content_model(root):
    """Fix element nesting that EPUB3's HTML5 schema rejects; returns True if changed."""
    ch = False
    for el in list(root.iter()):
        n = _local(el)
        if n is None or el.getparent() is None: continue
        ns = etree.QName(el).namespace
        # unknown elements in the XHTML namespace (Word smart tags etc.): unwrap, keep content
        if ns == XHTML and n not in HTML5:
            _unwrap(el); ch = True; continue
        # obsolete / misplaced attributes
        a = el.attrib
        st = a.get('style')
        if st is not None:
            parts = [x.strip() for x in st.split(';')]
            good = [x for x in parts if re.match(r'^[-\w]+\s*:\s*\S', x)]
            if len(good) != len([x for x in parts if x]):
                if good: a['style'] = '; '.join(good)
                else: del a['style']
                ch = True
        if n == 'a':
            for k in ('shape', 'coords', 'charset', 'rev'):
                if k in a: del a[k]; ch = True
        if n == 'li' and 'value' in a and _local(el.getparent()) != 'ol':
            del a['value']; ch = True
        if n == 'meta':
            ok = ('charset' in a) or ('content' in a and ('name' in a or 'itemprop' in a or 'property' in a))
            he = (a.get('http-equiv') or '').lower()
            # HTML5 keeps only these http-equiv states; XHTML 1.1 leftovers (Content-Style-Type, Content-Language ...) go
            bad_he = 'http-equiv' in a and he not in ('default-style', 'refresh', 'x-ua-compatible', 'content-security-policy')
            if he == 'content-type' or bad_he or (not ok and not ('http-equiv' in a and 'content' in a)):
                el.getparent().remove(el); ch = True; continue
    # at most one <meta charset>
    for m in root.xpath('//*[local-name()="meta"][@charset]')[1:]:
        m.getparent().remove(m); ch = True
    # lists: only <li> children; <li> only inside lists
    for lst in list(root.iter(H('ul'), H('ol'))):
        for c in list(lst):
            if isinstance(c.tag, str) and c.tag not in (H('li'), H('script'), H('template')):
                prev = c.getprevious()
                if prev is not None and prev.tag == H('li'):
                    prev.append(c)
                else:
                    li = etree.Element(H('li')); lst.replace(c, li); li.append(c)
                    li.tail, c.tail = c.tail, None
                ch = True
    for li in list(root.iter(H('li'))):
        if _local(li.getparent()) not in ('ul', 'ol', 'menu'):
            li.tag = H('div'); ch = True
    # tables: misplaced children
    TSECT = (H('thead'), H('tbody'), H('tfoot'))
    for t in list(root.iter(H('table'))):
        for c in list(t):
            if not isinstance(c.tag, str): continue
            if c.tag in (H('caption'), H('colgroup'), H('tr'), H('script'), H('template')) or c.tag in TSECT:
                if c.tag in TSECT:
                    for r in list(c):
                        if isinstance(r.tag, str) and r.tag not in (H('tr'), H('script'), H('template')):
                            c.remove(r); t.addprevious(r); ch = True
                continue
            t.remove(c); t.addprevious(c); ch = True
    for tr in list(root.iter(H('tr'))):
        for c in list(tr):
            if isinstance(c.tag, str) and c.tag not in (H('td'), H('th'), H('script'), H('template')):
                td = etree.Element(H('td')); tr.replace(c, td); td.append(c); td.tail, c.tail = c.tail, None; ch = True
    # deprecated / misplaced ARIA roles (epub:type keeps the semantics)
    for el in root.xpath('//*[@role]'):
        r = el.get('role')
        if _local(el) in ('body', 'html', 'head') or r in DEPRECATED_ROLES:
            del el.attrib['role']; ch = True
    for el in root.xpath('//*[@colspan or @rowspan]'):
        for k in ('colspan', 'rowspan'):
            v = el.get(k)
            if v is not None and not (v.strip().isdigit() and int(v) >= (1 if k == 'colspan' else 0)):
                del el.attrib[k]; ch = True
    # <tr> outside any table -> wrap runs in a table
    for tr in list(root.iter(H('tr'))):
        par = tr.getparent()
        if par is None or _local(par) in ('table', 'thead', 'tbody', 'tfoot'): continue
        tbl = etree.Element(H('table')); tr.addprevious(tbl)
        nxt = tr
        while nxt is not None and nxt.tag == H('tr'):
            after = nxt.getnext(); tbl.append(nxt); nxt = after
        ch = True
    # <col> must live in a <colgroup>
    for t in list(root.iter(H('table'))):
        run = []
        for c in list(t):
            if c.tag == H('col'):
                run.append(c)
            elif run:
                cg = etree.Element(H('colgroup')); t.insert(t.index(run[0]), cg)
                for r in run: cg.append(r)
                run = []; ch = True
        if run:
            cg = etree.Element(H('colgroup')); t.insert(t.index(run[0]), cg)
            for r in run: cg.append(r)
            ch = True
    # block content inside phrasing content
    for _ in range(4):
        moved = False
        for el in list(root.iter()):
            n = _local(el); par = el.getparent()
            if n not in BLOCK or par is None: continue
            pn = _local(par)
            if pn in PHRASING_PARENT:
                # the wrapper becomes a div (a block box already contains the block child)
                par.tag = H('div'); moved = True
            elif pn in HEADINGISH:
                el.tag = H('span'); _style(el, 'display: block'); moved = True
        ch |= moved
        if not moved: break
    return ch

def _clean_css(css, where, manifest):
    def dead(u):
        u = u.strip('\'" ')
        if re.match(r'^[a-zA-Z][\w+.-]*:', u) or u.startswith('#') or not u: return False
        return posixpath.normpath(posixpath.join(posixpath.dirname(where),
                                  unquote(u.split('?')[0].split('#')[0]))) not in manifest
    def ff(m):
        urls = re.findall(r'url\(([^)]*)\)', m.group(0))
        return '' if urls and all(dead(u) for u in urls) else m.group(0)
    c2 = re.sub(r'@font-face\s*\{[^}]*\}', ff, css)
    return re.sub(r'(?<=[;{\s])[\w-]+\s*:\s*[^;{}]*url\(([^)]*)\)[^;{}]*;?',
                  lambda m: '' if dead(m.group(1)) else m.group(0), c2)

def _repair_css(css):
    """Re-serialize a stylesheet with css_parser (as Sigil does) only if it has syntax errors."""
    import logging, css_parser
    class Count(logging.Handler):
        n = 0
        def emit(self, rec):
            if rec.levelno >= logging.ERROR: Count.n += 1
    log = logging.getLogger('css_repair'); log.handlers = [Count()]; log.propagate = False
    log.setLevel(logging.ERROR); Count.n = 0
    parser = css_parser.CSSParser(log=log, loglevel=logging.ERROR, validate=False, raiseExceptions=False)
    try:
        sheet = parser.parseString(css)
    except Exception:
        return css
    if not Count.n:
        return css
    css_parser.ser.prefs.useDefaults(); css_parser.ser.prefs.keepComments = True
    css_parser.ser.prefs.omitLastSemicolon = False
    out = sheet.cssText
    return out.decode('utf-8') if isinstance(out, bytes) else out

def run(files, items, opfp, opf):
    base = posixpath.dirname(opfp)
    manifest = {i['path'] for i in items if i['path'] in files}
    docs = [i for i in items if i['mt'] == 'application/xhtml+xml' and i['path'] in files]
    trees = {}
    for d in docs:
        try:
            trees[d['path']] = etree.fromstring(files[d['path']], PARSER)
        except etree.XMLSyntaxError:
            pass
    changed = set()
    navpaths = {i['path'] for i in items if 'nav' in i['props']}
    # 1. content model + valid ids (collect remaps)
    remap = {}  # (doc, old id) -> new id
    ids = {}
    for p, root in trees.items():
        if content_model(root): changed.add(p)
        if p in navpaths:
            # the EPUB nav-document schema forbids aria-label/aria-labelledby on <nav>
            # (RSC-005); keep the name as title, which is allowed (see a11y.py step 6)
            for nv in root.iter(H('nav')):
                lab = nv.attrib.pop('aria-label', None)
                ref = nv.attrib.pop('aria-labelledby', None)
                if lab is None and ref is None: continue
                if not nv.get('title'):
                    if not lab and ref:
                        hit = root.xpath('//*[@id=$i]', i=ref.split()[0])
                        lab = ' '.join(''.join(hit[0].itertext()).split()) if hit else ''
                    if lab: nv.set('title', lab)
                changed.add(p)
        seen = set(root.xpath('//@id'))
        for el in root.iter():
            if not isinstance(el.tag, str): continue
            i = el.get('id')
            if i is not None and not XMLNAME.match(i):
                new = re.sub(r'[^\w.\-]', '_', i, flags=re.U)
                if not XMLNAME.match(new): new = 'id_' + new
                k, cand = 2, new
                while cand in seen: cand = '%s_%d' % (new, k); k += 1
                seen.add(cand); remap[(p, i)] = cand; el.set('id', cand); changed.add(p)
        ids[p] = set(root.xpath('//@id'))
    # 2. links: remap fragments, drop dangling fragments, drop references to missing files
    def fix_href(src_doc, href):
        if re.match(r'^[a-zA-Z][\w+.-]*:', href): return href
        path, sep, frag = href.partition('#')
        tgt = posixpath.normpath(posixpath.join(posixpath.dirname(src_doc), unquote(path))) if path else src_doc
        if tgt not in manifest: return None
        if frag:
            frag_u = unquote(frag)
            if (tgt, frag_u) in remap: frag = remap[(tgt, frag_u)]
            elif tgt in ids and frag_u not in ids[tgt]:
                return path  # dangling fragment: keep the link to the document ('' for same-doc)
        return path + (sep + frag if frag else '')
    for p, root in trees.items():
        for el in root.iter(H('a')):
            h = el.get('href')
            if h is None or re.match(r'^[a-zA-Z][\w+.-]*:', h): continue
            nh = fix_href(p, h)
            if nh is None or nh == '':
                if p in navpaths:
                    li = el.getparent()
                    if nh is None and li is not None and li.tag == H('li') and li.find(H('ol')) is None:
                        li.getparent().remove(li); changed.add(p)
                    continue
                if nh is None:
                    del el.attrib['href']; changed.add(p)
                elif h.startswith('#'):
                    del el.attrib['href']; changed.add(p)
            elif nh != h:
                el.set('href', nh); changed.add(p)
        # cite="" holding editorial text rather than a URL -> keep it as a title
        for el in root.iter(H('ins'), H('del'), H('q'), H('blockquote')):
            c = el.get('cite')
            if c is not None and not re.match(r'^[a-zA-Z][\w+.-]*:', c):
                tgt = posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(c.split('#')[0])))
                if tgt not in manifest:
                    del el.attrib['cite']
                    if not el.get('title'): el.set('title', c)
                    changed.add(p)
        # scripts whose file is not in the book
        for el in list(root.iter(H('script'))):
            s0 = el.get('src')
            if s0 and not re.match(r'^[a-zA-Z][\w+.-]*:', s0) and \
               posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(s0))) not in manifest:
                el.getparent().remove(el); changed.add(p)
        # <a> nested inside <a>
        for el in list(root.iter(H('a'))):
            anc = el.getparent()
            while anc is not None and anc.tag != H('a'): anc = anc.getparent()
            if anc is not None:
                _unwrap(el); changed.add(p)
        # Kindle-internal links (kindle:pos:...) go nowhere in an EPUB: keep the text, drop the link
        for el in root.iter(H('a')):
            if (el.get('href') or '').startswith('kindle:'):
                del el.attrib['href']; changed.add(p)
        # remote URLs with whitespace in the host name
        for el in root.iter(H('a')):
            h = el.get('href') or ''
            m = re.match(r'^(https?://)([^/?#]*)(.*)$', h)
            if m and re.search(r'\s|%20', m.group(2)):
                el.set('href', m.group(1) + re.sub(r'\s|%20', '', m.group(2)) + m.group(3)); changed.add(p)
        # illegal characters in relative URLs -> percent-encode
        for el in root.iter():
            if not isinstance(el.tag, str): continue
            for k in ('href', 'src', '{http://www.w3.org/1999/xlink}href', 'poster'):
                v = el.get(k)
                if v and not re.match(r'^[a-zA-Z][\w+.-]*:', v) and re.search(r'[\s"<>\\^`{|}]', v):
                    el.set(k, quote(unquote(v), safe="/#:?=&;,+()'!*@$~%.-_")); changed.add(p)
        # inline <style>: drop @font-face/url() pointing at missing files
        for st in root.iter(H('style')):
            if st.text and 'url(' in st.text:
                t2 = _clean_css(st.text, p, manifest)
                if t2 != st.text: st.text = t2; changed.add(p)
        # images/resources that are not in the book: replace with their alt text
        for el in list(root.iter(H('img'))):
            s = el.get('src') or ''
            if re.match(r'^[a-zA-Z][\w+.-]*:', s) and not s.startswith('kindle:'): continue
            tgt = posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(s)))
            if tgt not in manifest:
                # the image never displayed; remove it without injecting new text
                par = el.getparent()
                if el.tail:
                    prev = el.getprevious()
                    if prev is not None: prev.tail = (prev.tail or '') + el.tail
                    else: par.text = (par.text or '') + el.tail
                par.remove(el); changed.add(p)
    for p in changed:
        files[p] = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' +
                    etree.tostring(trees[p], encoding='unicode')).encode('utf-8')
    # 3. CSS: @font-face / url() pointing at files that are not in the book
    for i in items:
        if i['mt'] != 'text/css' or i['path'] not in files: continue
        css = files[i['path']].decode('utf-8', 'replace')
        c2 = _repair_css(_clean_css(css, i['path'], manifest))
        if c2 != css: files[i['path']] = c2.encode('utf-8')
    # manifest 'scripted' must match actual scripts
    for d in docs:
        if 'scripted' in d['props'] and d['path'] in trees and not list(trees[d['path']].iter(H('script'))):
            newp = ' '.join(x for x in d['props'].split() if x != 'scripted')
            t2 = d['tag'].replace('properties="%s"' % d['props'], 'properties="%s"' % newp if newp else '')
            opf = opf.replace(d['tag'], re.sub(r'\s+properties=""', '', t2))
    # standalone SVG files: drop <image>s whose target is not in the book
    for i in items:
        if i['mt'] != 'image/svg+xml' or i['path'] not in files: continue
        try:
            sroot = etree.fromstring(files[i['path']], PARSER)
        except etree.XMLSyntaxError:
            continue
        gone = False
        for im in list(sroot.iter('{http://www.w3.org/2000/svg}image')):
            h = im.get('{http://www.w3.org/1999/xlink}href') or im.get('href') or ''
            if h.startswith('kindle:') or (not re.match(r'^[a-zA-Z][\w+.-]*:', h) and posixpath.normpath(
                    posixpath.join(posixpath.dirname(i['path']), unquote(h))) not in manifest):
                im.getparent().remove(im); gone = True
        if gone:
            files[i['path']] = etree.tostring(sroot, encoding='utf-8', xml_declaration=True)
    # 4. OPF: guide refs to non-XHTML/undeclared files; unreachable non-linear spine items
    xhtml_paths = {d['path'] for d in docs}
    def gref(m):
        h = re.search(r'href="([^"]*)"', m.group(0))
        if not h: return ''
        path, sep, frag = h.group(1).partition('#')
        tgt = posixpath.normpath(posixpath.join(base, unquote(path)))
        if tgt not in xhtml_paths: return ''
        if frag:
            fu = unquote(frag)
            if (tgt, fu) in remap: frag = remap[(tgt, fu)]
            elif tgt in ids and fu not in ids[tgt]: frag = ''
        return m.group(0).replace(h.group(0), 'href="%s"' % (path + ('#' + frag if frag else '')))
    # manifest entries whose file is missing
    for i in items:
        if i['path'] not in files and i['tag'] in opf:
            opf = opf.replace(i['tag'], '')
            opf = re.sub(r'\s*<itemref\b[^>]*idref="%s"[^>]*/>' % re.escape(i['id'] or ''), '', opf)
    # unique-identifier must resolve to a dc:identifier
    uidm = re.search(r'unique-identifier="([^"]+)"', opf)
    if uidm and not re.search(r'<dc:identifier\b[^>]*\bid="%s"' % re.escape(uidm.group(1)), opf):
        import uuid
        opf = opf.replace('</metadata>', '<dc:identifier id="%s">urn:uuid:%s</dc:identifier>\n</metadata>'
                          % (uidm.group(1), uuid.uuid4()), 1)
    opf = re.sub(r'\s*<reference\b[^>]*/>', gref, opf)
    opf = re.sub(r'\s*<guide>\s*</guide>', '', opf)
    linked = set()
    for p, root in trees.items():
        for el in root.iter(H('a')):
            h = el.get('href')
            if h and not re.match(r'^[a-zA-Z][\w+.-]*:', h):
                linked.add(posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(h.split('#')[0]))) if h.split('#')[0] else p)
    idpath = {i['id']: i['path'] for i in items}
    def lin(m):
        ir = re.search(r'idref="([^"]+)"', m.group(0)).group(1)
        return m.group(0) if idpath.get(ir) in linked else m.group(0).replace(' linear="no"', '')
    opf = re.sub(r'<itemref\b[^>]*linear="no"[^>]*/>', lin, opf)
    # 5. NCX: uid must match the OPF unique identifier, valid ids, pageList class
    uidref = re.search(r'unique-identifier="([^"]+)"', opf)
    uidval = None
    if uidref:
        m = re.search(r'<dc:identifier\b[^>]*id="%s"[^>]*>([^<]*)<' % re.escape(uidref.group(1)), opf)
        uidval = m and m.group(1).strip()
    for i in items:
        if i['mt'] != 'application/x-dtbncx+xml' or i['path'] not in files: continue
        x = files[i['path']].decode('utf-8', 'replace')
        if uidval:
            x = re.sub(r'(<meta\b[^>]*name="dtb:uid"[^>]*content=")[^"]*', lambda m: m.group(1) + uidval, x)
            x = re.sub(r'(<meta\b[^>]*content=")[^"]*("[^>]*name="dtb:uid")', lambda m: m.group(1) + uidval + m.group(2), x)
        x = re.sub(r'\bid="([^"]+)"', lambda m: m.group(0) if XMLNAME.match(m.group(1))
                   else 'id="%s"' % ('id_' + re.sub(r'[^\w.\-]', '_', m.group(1))), x)
        x = re.sub(r'<pageList(?![^>]*\bclass=)', '<pageList class="pagelist"', x)
        x = re.sub(r'<pageList(?![^>]*\bid=)', '<pageList id="ncx-page-list"', x)  # id is required (RSC-005)
        def csrc(m):
            h = m.group(2); path, sep, frag = h.partition('#')
            if not frag: return m.group(0)
            tgt = posixpath.normpath(posixpath.join(posixpath.dirname(i['path']), unquote(path)))
            fu = unquote(frag)
            if (tgt, fu) in remap: return m.group(1) + path + '#' + remap[(tgt, fu)] + m.group(3)
            if tgt in ids and fu not in ids[tgt]: return m.group(1) + path + m.group(3)
            return m.group(0)
        x = re.sub(r'(<content\b[^>]*\bsrc=")([^"]*)(")', csrc, x)
        try:
            nroot = etree.fromstring(x.encode('utf-8'), PARSER)
            NCX = '{http://www.daisy.org/z3986/2005/ncx/}'
            gone = False
            for npnt in list(nroot.iter(NCX + 'navPoint', NCX + 'pageTarget')):
                c = npnt.find(NCX + 'content')
                if c is None: continue
                t = posixpath.normpath(posixpath.join(posixpath.dirname(i['path']), unquote(c.get('src', '').split('#')[0])))
                if t not in manifest and npnt.find(NCX + 'navPoint') is None:
                    npnt.getparent().remove(npnt); gone = True
            if gone:
                x = etree.tostring(nroot, encoding='unicode', xml_declaration=False)
                x = '<?xml version="1.0" encoding="utf-8"?>\n' + x
                order = {}
                def po(m):
                    c = re.search(r'<content\b[^>]*src="([^"]*)"', x[m.end():])
                    key = c.group(1) if c else object()
                    if key not in order: order[key] = len(order) + 1
                    return 'playOrder="%d"' % order[key]
                x = re.sub(r'playOrder="\d+"', po, x)
        except etree.XMLSyntaxError:
            pass
        files[i['path']] = x.encode('utf-8')
    return opf
