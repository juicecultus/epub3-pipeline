"""Pre/post fixes around ePub3-itizer (runs under Sigil's bundled Python)."""
import os, re, sys, zipfile, posixpath

def _attr(tag, name):
    m = re.search(r'\b' + name + r'\s*=\s*"([^"]*)"', tag)
    return m.group(1) if m else None

def pre(root, opfpath):
    """Normalize the EPUB2 OPF the way Sigil does on load."""
    p = os.path.join(root, opfpath)
    s = open(p, encoding='utf-8', errors='replace').read()
    # 0a. any other prefix bound to the OPF namespace (e.g. p6:) -> opf:
    for pfx in set(re.findall(r'xmlns:(\w+)="http://www\.idpf\.org/2007/opf"', s)) - {'opf'}:
        s = re.sub(r'\s+xmlns:%s="http://www\.idpf\.org/2007/opf"' % pfx, '', s)
        s = re.sub(r'(?<=[\s<])%s:' % pfx, 'opf:', s)
        if 'xmlns:opf=' not in s:
            s = re.sub(r'<((?:opf:)?package\b)', r'<\1 xmlns:opf="http://www.idpf.org/2007/opf"', s, count=1)
    # 0b. elements knocked out of the OPF namespace
    s = re.sub(r'\s+xmlns=""', '', s)
    # 0c. empty unique-identifier -> urn:uuid
    uid = re.search(r'<(?:opf:)?package\b[^>]*unique-identifier="([^"]+)"', s)
    if uid:
        m = re.search(r'(<dc:identifier\b[^>]*\bid="%s"[^>]*>)\s*(</dc:identifier>)' % re.escape(uid.group(1)), s)
        m2 = re.search(r'<dc:identifier\b[^>]*\bid="%s"[^>]*/>' % re.escape(uid.group(1)), s)
        import uuid
        if m:
            s = s.replace(m.group(0), m.group(1) + 'urn:uuid:%s' % uuid.uuid4() + m.group(2))
        elif m2:
            s = s.replace(m2.group(0), m2.group(0)[:-2].rstrip() + '>urn:uuid:%s</dc:identifier>' % uuid.uuid4())
    # 1. opf:-prefixed elements -> default namespace
    if re.search(r'<opf:package\b', s):
        s = re.sub(r'<(/?)opf:', r'<\1', s)
        s = re.sub(r'<package\b', '<package xmlns="http://www.idpf.org/2007/opf"', s, count=1)
    base = posixpath.dirname(opfpath)
    items = re.findall(r'<item\b[^>]*>', s)
    seen, alias = {}, {}
    for t in items:
        iid, href = _attr(t, 'id'), _attr(t, 'href')
        if not iid or href is None: continue
        full = posixpath.normpath(posixpath.join(base, href.split('#')[0]))
        # 1b. manifest entry whose file is missing (Sigil drops these on load)
        from urllib.parse import unquote
        if not os.path.exists(os.path.join(root, unquote(full))):
            s = s.replace(t, ''); alias[iid] = None
            s = re.sub(r'<itemref\b[^>]*idref="%s"[^>]*/>\s*' % re.escape(iid), '', s)
            continue
        # 2. stale EPUB3 nav from an earlier export (plugin regenerates it)
        if 'nav' in (_attr(t, 'properties') or '') or posixpath.basename(full) == 'nav.xhtml':
            s = s.replace(t, ''); alias[iid] = None
            s = re.sub(r'<itemref\b[^>]*idref="%s"[^>]*/>\s*' % re.escape(iid), '', s)
            try: os.remove(os.path.join(root, full))
            except OSError: pass
            continue
        # 3. duplicate manifest entries for one file -> keep the first id
        if full in seen:
            s = s.replace(t, ''); alias[iid] = seen[full]
        else:
            seen[full] = iid
    for old, new in alias.items():
        if new:
            s = re.sub(r'(idref|content)="%s"' % re.escape(old), r'\1="%s"' % new, s)
    # 4. duplicate spine itemrefs -> keep the first
    refs = set()
    def dedupe(m):
        r = _attr(m.group(0), 'idref')
        if r in refs: return ''
        refs.add(r); return m.group(0)
    s = re.sub(r'<itemref\b[^>]*/>\s*', dedupe, s)
    s = safe_ids(s)
    s = safe_filenames(root, s, base)
    s = ensure_ncx(root, s, base)
    open(p, 'w', encoding='utf-8').write(s)
    repair_xhtml(root, s, base)

def ensure_ncx(root, opf, base):
    """EPUB2 requires an NCX (and ePub3-itizer builds the nav from it); Sigil creates one if missing."""
    from urllib.parse import unquote
    from xml.sax.saxutils import escape
    if re.search(r'media-type="application/x-dtbncx\+xml"', opf):
        return opf
    items = {_attr(t, 'id'): t for t in re.findall(r'<item\b[^>]*>', opf)}
    points = []
    for n, ref in enumerate(re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf), 1):
        t = items.get(ref)
        if not t or 'xhtml' not in (_attr(t, 'media-type') or ''): continue
        href = _attr(t, 'href')
        try:
            html = open(os.path.join(root, unquote(posixpath.join(base, href))), encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        m = re.search(r'<h[1-3]\b[^>]*>(.*?)</h[1-3]>', html, re.S) or re.search(r'<title[^>]*>(.*?)</title>', html, re.S)
        label = ' '.join(re.sub(r'<[^>]+>', '', m.group(1)).split()) if m else ''
        points.append((label or posixpath.splitext(posixpath.basename(href))[0], href))
    uid = re.search(r'unique-identifier="([^"]+)"', opf)
    uidv = uid and re.search(r'<dc:identifier\b[^>]*id="%s"[^>]*>([^<]*)<' % re.escape(uid.group(1)), opf)
    title = re.search(r'<dc:title[^>]*>(.*?)</dc:title>', opf, re.S)
    nav = ''.join('<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel><content src="%s"/></navPoint>\n'
                  % (i, i, escape(l), escape(h)) for i, (l, h) in enumerate(points, 1))
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
           '<head><meta name="dtb:uid" content="%s"/><meta name="dtb:depth" content="1"/>'
           '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>\n'
           '<docTitle><text>%s</text></docTitle>\n<navMap>\n%s</navMap>\n</ncx>\n'
           % (escape(uidv.group(1).strip() if uidv else ''), escape(re.sub(r'<[^>]+>', '', title.group(1)) if title else ''), nav))
    open(os.path.join(root, base, 'toc.ncx') if base else os.path.join(root, 'toc.ncx'), 'w', encoding='utf-8').write(ncx)
    nid = 'ncx' if 'ncx' not in items else 'ncx_generated'
    opf = re.sub(r'(</(?:opf:)?manifest>)', '<item id="%s" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n\\1' % nid, opf, count=1)
    opf = re.sub(r'<((?:opf:)?spine)\b(?![^>]*\btoc=)', r'<\1 toc="%s"' % nid, opf, count=1)
    return opf

def _xmlname(v):
    v2 = re.sub(r'[^A-Za-z0-9._-]', '_', v)
    return v2 if re.match(r'^[A-Za-z_]', v2) else 'id_' + v2

def safe_ids(opf):
    """Manifest ids must be XML names without colons; remap id/idref/cover/toc refs."""
    ids = set(re.findall(r'<item\b[^>]*\bid="([^"]+)"', opf))
    bad = {i: _xmlname(i) for i in ids if not re.match(r'^[A-Za-z_][A-Za-z0-9._-]*$', i)}
    taken = ids - set(bad)
    for o, n in list(bad.items()):
        k, c = 2, n
        while c in taken: c = '%s_%d' % (n, k); k += 1
        bad[o] = c; taken.add(c)
    for o, n in bad.items():
        q = re.escape(o)
        opf = re.sub(r'(<item\b[^>]*\bid=")%s"' % q, r'\g<1>%s"' % n, opf)
        opf = re.sub(r'(\b(?:idref|fallback|toc|media-overlay)=")%s"' % q, r'\g<1>%s"' % n, opf)
        opf = re.sub(r'(<meta\b[^>]*name="cover"[^>]*content=")%s"' % q, r'\g<1>%s"' % n, opf)
        opf = re.sub(r'(<meta\b[^>]*content=")%s("[^>]*name="cover")' % q, r'\g<1>%s\2' % n, opf)
    return opf

def safe_filenames(root, opf, base):
    """Rename resources whose names are not URL-safe; update every reference."""
    from urllib.parse import unquote, quote
    renames = {}
    taken = set()
    for dp, dn, fn in os.walk(root):
        taken.update(f.lower() for f in fn)
    for t in re.findall(r'<item\b[^>]*>', opf):
        href = _attr(t, 'href')
        if not href: continue
        name = posixpath.basename(unquote(href))
        if re.match(r'^[A-Za-z0-9._-]+$', name): continue
        stem, ext = os.path.splitext(name)
        new = re.sub(r'[^A-Za-z0-9._-]+', '_', stem).strip('_') or 'file'
        cand, k = new + ext, 2
        while cand.lower() in taken:
            cand = '%s_%d%s' % (new, k, ext); k += 1
        taken.add(cand.lower())
        old_path = os.path.join(root, unquote(posixpath.normpath(posixpath.join(base, href))))
        if os.path.isfile(old_path):
            os.rename(old_path, os.path.join(os.path.dirname(old_path), cand))
            renames[name] = cand
    if not renames:
        return opf
    forms = []
    for old, new in renames.items():
        for f in {old, quote(old), quote(old, safe="/,[]()'!&=+;@"), old.replace(' ', '%20')}:
            forms.append((f, new))
            forms.append((re.sub(r'%[0-9A-F]{2}', lambda m: m.group(0).lower(), f), new))
    forms.sort(key=lambda x: -len(x[0]))
    def sub(text):
        for f, new in forms:
            text = re.sub(r'(?<=[/"\'(=\s])' + re.escape(f) + r'(?=[#"\')\s?]|$)', new, text)
        return text
    opf = sub(opf)
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.lower().endswith(('.ncx', '.htm', '.html', '.xhtml', '.css', '.svg', '.xml', '.smil')):
                fp = os.path.join(dp, f)
                txt = open(fp, encoding='utf-8', errors='surrogateescape').read()
                t2 = sub(txt)
                if t2 != txt:
                    open(fp, 'w', encoding='utf-8', errors='surrogateescape').write(t2)
    return opf

def repair_xhtml(root, opf, base):
    """Like Sigil on load: mend any XHTML that is not well-formed via gumbo."""
    from modernize import parse_xhtml
    from urllib.parse import unquote
    for t in re.findall(r'<item\b[^>]*>', opf):
        if 'application/xhtml+xml' not in t: continue
        fp = os.path.join(root, unquote(posixpath.normpath(posixpath.join(base, _attr(t, 'href') or ''))))
        if not os.path.isfile(fp): continue
        data = open(fp, 'rb').read()
        st = dict(repaired=[])
        tree, repaired = parse_xhtml(data, st, fp)
        if repaired:
            from lxml import etree
            open(fp, 'wb').write(b'<?xml version="1.0" encoding="utf-8"?>\n' + etree.tostring(tree, encoding='utf-8'))

def post(epub):
    """Fix the generated EPUB3: nav out of spine, sane NCX playOrder/ids."""
    zin = zipfile.ZipFile(epub)
    files = {n: zin.read(n) for n in zin.namelist()}
    zin.close()
    c = files['META-INF/container.xml'].decode('utf-8', 'ignore')
    opfp = re.search(r'full-path="([^"]+)"', c).group(1)
    opf = files[opfp].decode('utf-8')
    nav = re.search(r'<item\b[^>]*properties="[^"]*\bnav\b[^"]*"[^>]*>', opf)
    if nav:
        nid = _attr(nav.group(0), 'id')
        opf = re.sub(r'<itemref\b[^>]*idref="%s"[^>]*/>\s*' % re.escape(nid), '', opf)
    opf = fix_cover(opf, opfp, files)
    files[opfp] = opf.encode('utf-8')
    for n in files:
        if n.endswith('.ncx'):
            x = files[n].decode('utf-8', 'ignore')
            # sequential playOrder; entries sharing a target share a number
            order = {}
            def po(m):
                c = re.search(r'<content\b[^>]*src="([^"]*)"', x[m.end():])
                key = c.group(1) if c else object()
                if key not in order: order[key] = len(order) + 1
                return 'playOrder="%d"' % order[key]
            x = re.sub(r'playOrder="\d+"', po, x)
            ids = {}
            def uid(m):
                v = m.group(1); ids[v] = ids.get(v, 0) + 1
                return m.group(0) if ids[v] == 1 else 'id="%s_%d"' % (v, ids[v])
            x = re.sub(r'\bid="([^"]+)"', uid, x)
            x = re.sub(r'\bid="([^"]+)"', lambda m: 'id="%s"' % _xmlname(m.group(1))
                       if not re.match(r'^[A-Za-z_][A-Za-z0-9._-]*$', m.group(1)) else m.group(0), x)
            files[n] = x.encode('utf-8')
    tmp = epub + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), files.pop('mimetype'), compress_type=zipfile.ZIP_STORED)
        for n, d in files.items():
            z.writestr(n, d, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, epub)

def fix_cover(opf, opfp, files):
    """If no manifest image is flagged cover-image, flag the image on the cover page."""
    if re.search(r'properties="[^"]*\bcover-image\b', opf): return opf
    base = posixpath.dirname(opfp)
    g = re.search(r'<reference\b[^>]*type="cover"[^>]*>', opf)
    page = _attr(g.group(0), 'href') if g else None
    if not page:  # fall back to first spine item
        first = re.search(r'<itemref\b[^>]*idref="([^"]+)"', opf)
        it = first and re.search(r'<item\b[^>]*id="%s"[^>]*>' % re.escape(first.group(1)), opf)
        page = it and _attr(it.group(0), 'href')
    if not page: return opf
    pp = posixpath.normpath(posixpath.join(base, page.split('#')[0]))
    html = files.get(pp, b'').decode('utf-8', 'ignore')
    m = re.search(r'<img\b[^>]*\bsrc="([^"]+)"|<image\b[^>]*href="([^"]+)"', html)
    if not m: return opf
    img = posixpath.normpath(posixpath.join(posixpath.dirname(pp), m.group(1) or m.group(2)))
    for t in re.findall(r'<item\b[^>]*>', opf):
        h = _attr(t, 'href')
        if h and posixpath.normpath(posixpath.join(base, h)) == img and 'image/' in (_attr(t, 'media-type') or ''):
            props = _attr(t, 'properties')
            nt = (t.replace('properties="%s"' % props, 'properties="%s cover-image"' % props) if props
                  else re.sub(r'\s*/?>$', ' properties="cover-image" />', t))
            opf = opf.replace(t, nt)
            iid = _attr(t, 'id')
            if re.search(r'<meta\b[^>]*name="cover"', opf):
                opf = re.sub(r'(<meta\b[^>]*name="cover"[^>]*content=")[^"]*', r'\g<1>' + iid, opf)
                opf = re.sub(r'(<meta\b[^>]*content=")[^"]*("[^>]*name="cover")', r'\g<1>' + iid + r'\2', opf)
            else:
                opf = opf.replace('</metadata>', '<meta name="cover" content="%s" />\n</metadata>' % iid, 1)
            break
    return opf
