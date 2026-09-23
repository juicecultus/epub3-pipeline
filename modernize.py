#!/usr/bin/env python3
"""Modernize an EPUB3 in place: Sigil-style XHTML repair, obsolete HTML -> CSS,
unique ids, lang attributes, nav landmarks, and EPUB Accessibility 1.1 discovery
metadata derived from the actual content.  Run under Sigil's bundled Python
(needs lxml and Sigil's gumbo adapter)."""
import os, re, sys, zipfile, posixpath, datetime
from urllib.parse import unquote
from lxml import etree

SIGIL = '/Applications/Sigil.app/Contents'
sys.path.insert(0, SIGIL + '/plugin_launchers/python')
os.environ.setdefault('SigilGumboLibPath', SIGIL + '/lib/libsigilgumbo.dylib')
import sigil_gumbo_bs4_adapter as gumbo_bs4

XHTML = 'http://www.w3.org/1999/xhtml'
EPUB = 'http://www.idpf.org/2007/ops'
OPF = 'http://www.idpf.org/2007/opf'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
H = lambda t: '{%s}%s' % (XHTML, t)
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True,
                         remove_blank_text=False, recover=False)

def _local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else None

def _len(v):
    v = v.strip()
    return v if v.endswith('%') or not v else (v if re.search(r'[a-z]', v) else v + 'px')

def _add_style(el, decl):
    cur = (el.get('style') or '').strip().rstrip(';')
    prop = decl.split(':')[0].strip()
    if re.search(r'(^|;)\s*' + re.escape(prop) + r'\s*:', cur):
        return  # author style wins
    el.set('style', (cur + '; ' if cur else '') + decl)

FONT_SIZES = {'1': 'x-small', '2': 'small', '3': 'medium', '4': 'large', '5': 'x-large',
              '6': 'xx-large', '7': 'xxx-large', '-2': 'smaller', '-1': 'smaller',
              '+1': 'larger', '+2': 'larger', '+3': 'x-large', '+4': 'xx-large'}
TABLEISH = {'table', 'td', 'th', 'tr', 'col', 'colgroup', 'tbody', 'thead', 'tfoot'}
IMG_ATTRS = {'src', 'alt', 'width', 'height', 'id', 'class', 'style', 'title', 'lang', 'dir', 'role',
             'srcset', 'sizes', 'usemap', 'ismap', 'loading', 'decoding', 'crossorigin', 'referrerpolicy',
             'hidden', 'tabindex', 'translate', 'fetchpriority'}
PHRASING = {'p', 'span', 'a', 'b', 'i', 'em', 'strong', 'small', 'sub', 'sup', 'u', 's', 'cite', 'q',
            'abbr', 'code', 'label', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'dt', 'font', 'big', 'tt'}
BLOCK_ALIGN = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th', 'tr', 'caption',
               'tbody', 'thead', 'tfoot', 'col', 'colgroup', 'legend', 'hr'}

def modernize_html(root, stats):
    """Convert obsolete presentational HTML to CSS; returns True if changed."""
    changed = False
    for el in list(root.iter()):
        n = _local(el)
        if n is None:
            continue
        a = el.attrib
        def pop(k):
            nonlocal changed
            changed = True
            return a.pop(k)
        if n == 'table':
            if 'cellspacing' in a:
                v = pop('cellspacing'); _add_style(el, 'border-spacing: %s' % _len(v))
                if _len(v) in ('0', '0px'): _add_style(el, 'border-collapse: collapse')
            if 'cellpadding' in a:
                v = _len(pop('cellpadding'))
                for c in el.iter(H('td'), H('th')):
                    _add_style(c, 'padding: %s' % v)
            if 'border' in a and a['border'] not in ('', '1'):
                v = pop('border')
                if v.strip() not in ('0', ''):
                    _add_style(el, 'border: %s solid' % _len(v))
            if 'frame' in a: pop('frame')
            if 'rules' in a: pop('rules')
            if 'summary' in a: pop('summary')
            if 'align' in a:
                v = pop('align').lower()
                if v == 'center': _add_style(el, 'margin-left: auto'); _add_style(el, 'margin-right: auto')
                elif v in ('left', 'right'): _add_style(el, 'float: %s' % v)
        if n in TABLEISH or n in ('hr', 'pre', 'div', 'p', 'iframe'):
            for k in ('width', 'height'):
                if k in a and n not in ('iframe',):
                    _add_style(el, '%s: %s' % (k, _len(pop(k))))
        if 'valign' in a:
            _add_style(el, 'vertical-align: %s' % pop('valign').lower())
        if 'align' in a and n in BLOCK_ALIGN:
            v = pop('align').lower()
            _add_style(el, ('text-align: %s' % v) if v != 'char' else 'text-align: center')
        if 'align' in a and n in ('img', 'object', 'embed', 'iframe', 'input'):
            v = pop('align').lower()
            if v in ('left', 'right'): _add_style(el, 'float: %s' % v)
            elif v in ('top', 'middle', 'bottom', 'baseline'): _add_style(el, 'vertical-align: %s' % v)
        if 'bgcolor' in a:
            _add_style(el, 'background-color: %s' % pop('bgcolor'))
        if 'nowrap' in a:
            pop('nowrap'); _add_style(el, 'white-space: nowrap')
        if n == 'img':
            for k in ('border', 'hspace', 'vspace'):
                if k in a:
                    v = _len(pop(k))
                    _add_style(el, {'border': 'border: %s solid' % v,
                                    'hspace': 'margin-left: %s; margin-right: %s' % (v, v),
                                    'vspace': 'margin-top: %s; margin-bottom: %s' % (v, v)}[k])
            if 'longdesc' in a: pop('longdesc')
        if n == 'hr':
            if 'noshade' in a: pop('noshade')
            if 'size' in a: _add_style(el, 'height: %s' % _len(pop('size')))
            if 'color' in a: _add_style(el, 'color: %s' % pop('color'))
        if n == 'br' and 'clear' in a:
            v = pop('clear').lower(); _add_style(el, 'clear: %s' % ('both' if v == 'all' else v))
        if n in ('ul', 'ol', 'li') and 'type' in a and n != 'ol':
            v = pop('type').lower(); _add_style(el, 'list-style-type: %s' % v)
        if n in ('ul', 'ol', 'dl', 'menu', 'dir') and 'compact' in a:
            pop('compact')
        if n == 'a' and 'name' in a:
            v = pop('name')
            if 'id' not in a and v and v not in stats['ids']:
                el.set('id', v); stats['ids'].add(v)
        if n in ('script',) and 'language' in a:
            pop('language')
        if n == 'html' and 'version' in a:
            pop('version')
        if n in ('head', 'body') and 'profile' in a:
            pop('profile')
        if n == 'body':
            for k, css in (('bgcolor', 'background-color'), ('text', 'color'), ('link', None),
                           ('vlink', None), ('alink', None), ('background', None)):
                if k in a:
                    v = pop(k)
                    if css: _add_style(el, '%s: %s' % (css, v))
        # integer-only width/height on embedded content
        if n in ('img', 'video', 'canvas', 'iframe', 'embed', 'object', 'input', 'source'):
            for k in ('width', 'height'):
                if k in a and not re.match(r'^\d+$', a[k].strip()):
                    v = a[k].strip()
                    if re.match(r'^\d+(\.\d+)?px$', v): a[k] = str(int(float(v[:-2]))); changed = True
                    else: _add_style(el, '%s: %s' % (k, _len(pop(k))))
        # custom data attributes must be lowercase / XML-compatible
        for k in [k for k in a.keys() if k.startswith('data-') and (k != k.lower() or k == 'data-')]:
            v = pop(k)
            if k.lower() not in a and k != 'data-': a[k.lower()] = v
        # obsolete elements
        if n == 'center':
            el.tag = H('div'); _add_style(el, 'text-align: center'); changed = True
        elif n == 'font':
            el.tag = H('span'); changed = True
            if 'color' in a: _add_style(el, 'color: %s' % a.pop('color'))
            if 'face' in a: _add_style(el, 'font-family: %s' % a.pop('face'))
            if 'size' in a: _add_style(el, 'font-size: %s' % FONT_SIZES.get(a.pop('size').strip(), 'medium'))
        elif n == 'big':
            el.tag = H('span'); _add_style(el, 'font-size: larger'); changed = True
        elif n == 'tt':
            el.tag = H('span'); _add_style(el, 'font-family: monospace'); changed = True
        elif n in ('strike',):
            el.tag = H('s'); changed = True
        elif n == 'acronym':
            el.tag = H('abbr'); changed = True
    return changed

def strip_office(root):
    """Remove MS Word export debris: conditional comments, VML/Office elements."""
    changed = False
    for c in list(root.iter(etree.Comment)):
        t = (c.text or '').strip()
        if t.startswith('[if') or t.startswith('[endif') or t.startswith('<![endif'):
            _remove_keep_tail(c); changed = True
    for el in list(root.iter()):
        if not isinstance(el.tag, str) or not el.tag.startswith('{'): continue
        ns = el.tag[1:].split('}')[0]
        if 'schemas-microsoft-com' in ns or 'schemas.microsoft.com' in ns:
            if el.getparent() is None: continue
            if etree.QName(el).localname == 'p':  # <o:p> wraps real text: unwrap
                _unwrap(el)
            else:
                _remove_keep_tail(el)
            changed = True
    for el in root.iter():
        if not isinstance(el.tag, str): continue
        for k in list(el.attrib):
            if k.startswith('{') and ('schemas-microsoft-com' in k or 'schemas.microsoft.com' in k):
                del el.attrib[k]; changed = True
        if el.tag == H('img'):
            for k in list(el.attrib):
                if not (k in IMG_ATTRS or k.startswith(('aria-', 'data-', '{'))):
                    del el.attrib[k]; changed = True
    for m in list(root.iter(H('meta'))):
        if (m.get('name') or '') in ('ProgId', 'Generator', 'Originator'):
            _remove_keep_tail(m); changed = True
    return changed

def _remove_keep_tail(el):
    par = el.getparent()
    if par is None: return
    if el.tail:
        prev = el.getprevious()
        if prev is not None: prev.tail = (prev.tail or '') + el.tail
        else: par.text = (par.text or '') + el.tail
    par.remove(el)

def _unwrap(el):
    par = el.getparent(); idx = par.index(el)
    text = (el.text or '')
    prev = el.getprevious()
    if prev is not None: prev.tail = (prev.tail or '') + text
    else: par.text = (par.text or '') + text
    for i, ch in enumerate(list(el)):
        par.insert(idx + i, ch)
    _remove_keep_tail(el)

def dedupe_ids(root, seen_global):
    changed = False
    seen = set()
    for el in root.iter():
        if not isinstance(el.tag, str): continue
        i = el.get('id')
        if i is None: continue
        if i in seen or not re.match(r'^[^\s]+$', i):
            base = re.sub(r'\s+', '_', i) or 'id'
            k = 2
            while '%s_%d' % (base, k) in seen: k += 1
            el.set('id', '%s_%d' % (base, k)); i = el.get('id'); changed = True
        seen.add(i)
    return changed, seen

def parse_xhtml(data, stats, path):
    """Return lxml tree; repair with Sigil's gumbo parser if not well-formed."""
    try:
        return etree.fromstring(data, PARSER), False
    except etree.XMLSyntaxError:
        text = data.decode('utf-8', 'replace')
        # '--' is illegal inside comments; neutralize before trying again
        text = re.sub(r'<!--(.*?)-->', lambda m: '<!--' + re.sub(r'-(?=-)', '- ', m.group(1)).strip('-') + '-->',
                      text, flags=re.S)
        try:
            stats['repaired'].append(path)
            return etree.fromstring(text.encode('utf-8'), PARSER), True
        except etree.XMLSyntaxError:
            stats['repaired'].pop()
        soup = gumbo_bs4.parse(text)
        fixed = soup.serialize_xhtml()
        stats['repaired'].append(path)
        return etree.fromstring(fixed.encode('utf-8') if isinstance(fixed, str) else fixed, PARSER), True

def serialize(root):
    body = etree.tostring(root, encoding='unicode')
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' + body).encode('utf-8')

def modernize(epub_path):
    zin = zipfile.ZipFile(epub_path)
    names = zin.namelist()
    files = {n: zin.read(n) for n in names}
    zin.close()
    c = files['META-INF/container.xml'].decode('utf-8', 'ignore')
    opfp = re.search(r'full-path="([^"]+)"', c).group(1)
    base = posixpath.dirname(opfp)
    opf = files[opfp].decode('utf-8')
    items = []
    for t in re.findall(r'<item\b[^>]*>', opf):
        g = lambda k: (re.search(r'\b%s="([^"]*)"' % k, t) or [None, None])[1]
        items.append(dict(tag=t, id=g('id'), href=g('href'), mt=g('media-type') or '',
                          props=g('properties') or '',
                          path=posixpath.normpath(posixpath.join(base, unquote(g('href') or '')))))
    lang = (re.search(r'<dc:language[^>]*>([^<]+)</dc:language>', opf) or [None, None])[1]
    if not lang:
        lang = 'en'
        opf = opf.replace('</metadata>', '<dc:language>en</dc:language>\n</metadata>', 1)
    lang = lang.strip()
    book_title = re.sub(r'<[^>]+>', '', (re.search(r'<dc:title[^>]*>(.*?)</dc:title>', opf, re.S) or [None, 'Untitled'])[1]).strip() or 'Untitled'
    # leftover EPUB2 OPF attributes that EPUB3 does not allow
    opf = re.sub(r'\s+xsi:type="[^"]*"', '', opf)
    opf = re.sub(r'\s+xmlns:xsi="[^"]*"', '', opf)
    opf = re.sub(r'(<item\b[^>]*?)\s+fallback-style="[^"]*"', r'\1', opf)
    while True:
        o2 = re.sub(r'(<dc:\w+\b[^>]*?)\s+opf:\w[\w-]*="[^"]*"', r'\1', opf)
        if o2 == opf: break
        opf = o2
    manifest_paths = {i['path'] for i in items}
    stats = dict(repaired=[], ids=set(), imgs=0, imgs_alt=0, headings=0, tables=0,
                 mathml=False, svg=False, media=False, script=False, pagebreaks=False)
    changed_files = set()
    for it in items:
        if it['mt'] != 'application/xhtml+xml' or it['path'] not in files: continue
        root, repaired = parse_xhtml(files[it['path']], stats, it['path'])
        ch = repaired
        # lang / xml:lang on <html>
        if not root.get('lang') and not root.get(XML_LANG):
            root.set('lang', lang); root.set(XML_LANG, lang); ch = True
        elif root.get(XML_LANG) and not root.get('lang'):
            root.set('lang', root.get(XML_LANG)); ch = True
        elif root.get('lang') and not root.get(XML_LANG):
            root.set(XML_LANG, root.get('lang')); ch = True
        if 'nav' not in it['props']:
            ch |= modernize_html(root, stats)
            # <link>s to files that are not in the book (Word export debris)
            for ln in list(root.iter(H('link'))):
                href = ln.get('href') or ''
                tgt = posixpath.normpath(posixpath.join(posixpath.dirname(it['path']), unquote(href.split('#')[0])))
                rel = (ln.get('rel') or '').lower().split()
                if re.match(r'^[a-z]+:', href) or tgt not in manifest_paths or 'stylesheet' not in rel:
                    ln.getparent().remove(ln); ch = True
            # block <div> inside phrasing content -> <span style="display:block">
            for dv in list(root.iter(H('div'))):
                par = dv.getparent()
                if par is not None and _local(par) in PHRASING:
                    dv.tag = H('span'); _add_style(dv, 'display: block'); ch = True
            ch |= strip_office(root)
            etree.cleanup_namespaces(root)
        # <title> must not be empty
        head = root.find(H('head'))
        if head is not None:
            t = head.find(H('title'))
            if t is None:
                t = etree.Element(H('title')); head.insert(0, t)
            if not (t.text or '').strip() and not len(t):
                hx = next((''.join(e.itertext()).strip() for e in root.iter(H('h1'), H('h2'), H('h3'))
                           if ''.join(e.itertext()).strip()), '')
                t.text = hx or book_title; ch = True
        d, _ = dedupe_ids(root, stats['ids']); ch |= d
        # content inventory for accessibility metadata
        for el in root.iter():
            n = _local(el)
            if n == 'img':
                stats['imgs'] += 1
                alt = (el.get('alt') or '').strip()
                if alt and not re.match(r'(?i)^(.*\.(jpe?g|png|gif|svg|webp)|(image|img|picture|pic|graphic|'
                                        r'illustration|photo|figure|fig|cover|logo|untitled)?[\s_\-]*\d*)$', alt):
                    stats['imgs_alt'] += 1
                else:  # leave it missing: an empty alt would falsely mark it decorative
                    stats['imgs_alt_missing'] = stats.get('imgs_alt_missing', 0) + 1
            elif n in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'): stats['headings'] += 1
            elif n == 'table': stats['tables'] += 1
            elif n == 'math': stats['mathml'] = True
            elif n == 'svg': stats['svg'] = True
            elif n in ('audio', 'video'): stats['media'] = True
            elif n == 'script': stats['script'] = True
            if isinstance(el.tag, str) and 'pagebreak' in (el.get('{%s}type' % EPUB) or ''):
                stats['pagebreaks'] = True
        if ch:
            files[it['path']] = serialize(root); changed_files.add(it['path'])

    # nav: landmarks with toc + bodymatter, no empty lists
    nav = next((i for i in items if 'nav' in i['props']), None)
    has_pagelist = False
    if nav and nav['path'] in files:
        root = etree.fromstring(files[nav['path']], PARSER)
        for ol in list(root.iter(H('ol'))):
            if not len(ol.findall(H('li'))):
                ol.getparent().remove(ol)
        for a in list(root.iter(H('a'))):  # nav anchors must contain text
            if not ''.join(a.itertext()).strip():
                if len(a) == 0: a.text = 'Section'
                else: a.set('title', 'Section'); a.insert(0, etree.Element(H('span'))); a[0].text = 'Section'
        navs = {n.get('{%s}type' % EPUB): n for n in root.iter(H('nav'))}
        has_pagelist = 'page-list' in navs and len(list(navs['page-list'].iter(H('a')))) > 0
        toc = navs.get('toc')
        lm = navs.get('landmarks')
        body = root.find(H('body'))
        if lm is None:
            lm = etree.SubElement(body, H('nav')); lm.set('{%s}type' % EPUB, 'landmarks')
            lm.set('id', 'landmarks'); lm.set('hidden', '')
            h = etree.SubElement(lm, H('h2')); h.text = 'Guide'
            etree.SubElement(lm, H('ol'))
        lol = lm.find(H('ol'))
        if lol is None: lol = etree.SubElement(lm, H('ol'))
        types = {a.get('{%s}type' % EPUB) for a in lm.iter(H('a'))}
        navname = posixpath.basename(nav['path'])
        if 'toc' not in types and toc is not None:
            # nav.xhtml is not in the spine, so point at the book's own contents page if any
            for a0 in toc.iter(H('a')):
                if re.match(r'^\s*(table of )?contents\s*$', ''.join(a0.itertext()), re.I) and a0.get('href'):
                    li = etree.SubElement(lol, H('li')); a = etree.SubElement(li, H('a'))
                    a.set('{%s}type' % EPUB, 'toc'); a.set('href', a0.get('href')); a.text = 'Table of Contents'
                    break
        if 'bodymatter' not in types and toc is not None:
            front = re.compile(r'^\s*(cover|title|title page|copyright|contents|table of contents|dedication|'
                               r'epigraph|also by|praise|about the (author|publisher)|acknowledg|'
                               r'(a )?note|preface|foreword|introduction|map|maps|half title|frontispiece|'
                               r'other books|books by|by the same|list of|chronology|translator|'
                               r'further reading|abbreviations|cast of|dramatis|editor)', re.I)
            for a in toc.iter(H('a')):
                label = ''.join(a.itertext()).strip()
                if label and not front.match(label) and a.get('href'):
                    li = etree.SubElement(lol, H('li')); b = etree.SubElement(li, H('a'))
                    b.set('{%s}type' % EPUB, 'bodymatter'); b.set('href', a.get('href')); b.text = 'Start of Content'
                    break
        if not len(lol.findall(H('li'))):
            lm.getparent().remove(lm)
        if not root.get('lang'):
            root.set('lang', lang); root.set(XML_LANG, lang)
        files[nav['path']] = serialize(root)

    import hygiene
    opf = hygiene.run(files, items, opfp, opf)
    if 'cover-image' not in opf:
        import fixes
        opf = fixes.fix_cover(opf, opfp, files)
    if 'cover-image' not in opf:
        cands = [i for i in items if i['mt'].startswith('image/') and i['path'] in files
                 and re.search(r'cover', posixpath.basename(i['path']), re.I)]
        if cands:
            c0 = max(cands, key=lambda i: len(files[i['path']]))
            nt = (c0['tag'].replace('properties="%s"' % c0['props'], 'properties="%s cover-image"' % c0['props'])
                  if c0['props'] else re.sub(r'\s*/?>$', ' properties="cover-image" />', c0['tag']))
            opf = opf.replace(c0['tag'], nt)
            if not re.search(r'<meta\b[^>]*name="cover"', opf):
                opf = opf.replace('</metadata>', '<meta name="cover" content="%s" />\n</metadata>' % c0['id'], 1)

    import a11y
    opf, _ = a11y.run(files, items, opfp, opf, book_title)
    if nav and nav['path'] in files:
        nr = etree.fromstring(files[nav['path']], PARSER)
        has_pagelist = any('page-list' in (n.get('{%s}type' % EPUB) or '') and len(list(n.iter(H('a'))))
                           for n in nr.iter(H('nav')))
    # recount images / text alternatives after the accessibility fixes
    stats['imgs'] = stats['imgs_alt'] = 0
    for it in items:
        if it['mt'] != 'application/xhtml+xml' or it['path'] not in files or 'nav' in it['props']: continue
        try:
            r0 = etree.fromstring(files[it['path']], PARSER)
        except etree.XMLSyntaxError:
            continue
        for el in r0.iter(H('img')):
            stats['imgs'] += 1
            alt = (el.get('alt') or '').strip()
            if alt and not re.match(r'(?i)^(.*\.(jpe?g|png|gif|svg|webp)|(image|img|picture|pic|graphic|'
                                    r'illustration|photo|figure|fig|cover|logo|untitled)?[\s_\-]*\d*)$', alt):
                stats['imgs_alt'] += 1
    stats['imgs_alt_missing'] = stats['imgs'] - stats['imgs_alt']

    # accessibility discovery metadata (EPUB Accessibility 1.1 / schema.org)
    opf = re.sub(r'\s*<meta property="schema:access[^"]*"[^>]*>[^<]*</meta>', '', opf)
    opf = re.sub(r'\s*<meta property="schema:accessibility[^"]*"[^>]*>[^<]*</meta>', '', opf)
    has_img = stats['imgs'] > 0 or stats['svg']
    all_alt = stats['imgs'] == stats['imgs_alt']
    modes = ['textual'] + (['visual'] if has_img else [])
    sufficient = ['textual'] if (not has_img or all_alt) else []
    if has_img: sufficient.append('textual,visual')
    feats = ['readingOrder', 'displayTransformability']
    if stats['headings']: feats.append('structuralNavigation')
    if nav: feats.append('tableOfContents')
    if has_img and all_alt and stats['imgs']: feats.append('alternativeText')
    if has_pagelist: feats += ['pageNavigation', 'printPageNumbers']
    if stats['mathml']: feats.append('MathML')
    hazard = 'unknown' if (stats['media'] or stats['script']) else 'none'
    parts = ['a navigable table of contents'] + (['structured headings'] if stats['headings'] else []) \
        + (['print page references'] if has_pagelist else [])
    summary = ('Reflowable EPUB 3 publication with %s. Text can be resized and restyled by the reading system.%s' % (
        ', '.join(parts[:-1]) + (' and ' if len(parts) > 1 else '') + parts[-1],
        (' Contains %d image%s; %s.' % (stats['imgs'], 's' if stats['imgs'] != 1 else '',
          'all have text descriptions' if all_alt else
          '%d of them %s a text description' % (stats['imgs'] - stats['imgs_alt'],
                                               'lacks' if stats['imgs'] - stats['imgs_alt'] == 1 else 'lack')))
        if stats['imgs'] else ''))
    meta = []
    meta += ['<meta property="schema:accessMode">%s</meta>' % m for m in modes]
    meta += ['<meta property="schema:accessModeSufficient">%s</meta>' % m for m in sufficient]
    meta += ['<meta property="schema:accessibilityFeature">%s</meta>' % f for f in feats]
    meta += ['<meta property="schema:accessibilityHazard">%s</meta>' % hazard]
    meta += ['<meta property="schema:accessibilitySummary">%s</meta>' % summary]
    if 'xmlns:schema' not in opf and 'schema: http' not in opf:
        opf = re.sub(r'(<package\b[^>]*prefix=")', r'\1schema: http://schema.org/ ', opf, count=1) \
            if 'prefix="' in re.search(r'<package\b[^>]*>', opf).group(0) else \
            re.sub(r'<package\b', '<package prefix="schema: http://schema.org/"', opf, count=1)
    now = datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    opf = re.sub(r'(<meta property="dcterms:modified">)[^<]*(</meta>)', r'\g<1>' + now + r'\2', opf)
    opf = opf.replace('</metadata>', '\n'.join(meta) + '\n</metadata>', 1)
    files[opfp] = opf.encode('utf-8')

    tmp = epub_path + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), files.pop('mimetype', b'application/epub+zip'),
                   compress_type=zipfile.ZIP_STORED)
        for n in names:
            if n in files:
                z.writestr(n, files[n], compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, epub_path)
    return dict(repaired=stats['repaired'], changed=len(changed_files), imgs=stats['imgs'],
                alt_missing=stats.get('imgs_alt_missing', 0))

if __name__ == '__main__':
    print(modernize(sys.argv[1]))
