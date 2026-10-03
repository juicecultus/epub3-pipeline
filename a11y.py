"""Accessibility fixes driven by Ace by DAISY findings.  Runs inside modernize()
on the in-memory {zip name: bytes} map.  No visible text is changed."""
import re, posixpath, colorsys
from urllib.parse import unquote
from lxml import etree

XHTML = 'http://www.w3.org/1999/xhtml'
EPUB_T = '{http://www.idpf.org/2007/ops}type'
H = lambda t: '{%s}%s' % (XHTML, t)
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)

# epub:type -> DPUB-ARIA role, and the elements on which HTML-ARIA allows that role
ROLE = {
    'abstract': 'doc-abstract', 'acknowledgments': 'doc-acknowledgments', 'afterword': 'doc-afterword',
    'appendix': 'doc-appendix', 'backlink': 'doc-backlink', 'bibliography': 'doc-bibliography',
    'biblioref': 'doc-biblioref', 'chapter': 'doc-chapter', 'colophon': 'doc-colophon',
    'conclusion': 'doc-conclusion', 'cover': 'doc-cover', 'credit': 'doc-credit', 'credits': 'doc-credits',
    'dedication': 'doc-dedication', 'endnotes': 'doc-endnotes', 'epigraph': 'doc-epigraph',
    'epilogue': 'doc-epilogue', 'errata': 'doc-errata', 'example': 'doc-example', 'footnote': 'doc-footnote',
    'foreword': 'doc-foreword', 'glossary': 'doc-glossary', 'glossref': 'doc-glossref', 'index': 'doc-index',
    'introduction': 'doc-introduction', 'noteref': 'doc-noteref', 'notice': 'doc-notice',
    'pagebreak': 'doc-pagebreak', 'page-list': 'doc-pagelist', 'part': 'doc-part', 'preface': 'doc-preface',
    'prologue': 'doc-prologue', 'pullquote': 'doc-pullquote', 'qna': 'doc-qna', 'subtitle': 'doc-subtitle',
    'tip': 'doc-tip', 'toc': 'doc-toc',
}
ANY_ROLE = {'div', 'span', 'p', 'b', 'i', 'em', 'strong', 'small', 'blockquote', 'figure', 'pre', 'dl', 'table'}
SECTION_OK = {'doc-abstract', 'doc-acknowledgments', 'doc-afterword', 'doc-appendix', 'doc-bibliography',
              'doc-chapter', 'doc-colophon', 'doc-conclusion', 'doc-credit', 'doc-credits', 'doc-dedication',
              'doc-endnotes', 'doc-epigraph', 'doc-epilogue', 'doc-errata', 'doc-example', 'doc-foreword',
              'doc-glossary', 'doc-index', 'doc-introduction', 'doc-notice', 'doc-pagelist', 'doc-part',
              'doc-preface', 'doc-prologue', 'doc-pullquote', 'doc-qna', 'doc-toc'}
ALLOWED = {
    'section': SECTION_OK, 'article': SECTION_OK,
    'aside': {'doc-dedication', 'doc-example', 'doc-footnote', 'doc-glossary', 'doc-pullquote', 'doc-tip'},
    'nav': {'doc-index', 'doc-pagelist', 'doc-toc'},
    'a': {'doc-backlink', 'doc-biblioref', 'doc-glossref', 'doc-noteref'},
    'hr': {'doc-pagebreak'}, 'img': {'doc-cover'},
    'header': {'doc-footnote'}, 'footer': {'doc-footnote'},
    'h1': {'doc-subtitle'}, 'h2': {'doc-subtitle'}, 'h3': {'doc-subtitle'}, 'h4': {'doc-subtitle'},
    'h5': {'doc-subtitle'}, 'h6': {'doc-subtitle'},
}
LANG3 = {'eng': 'en', 'fre': 'fr', 'fra': 'fr', 'rus': 'ru', 'ger': 'de', 'deu': 'de', 'spa': 'es',
         'ita': 'it', 'por': 'pt', 'lat': 'la', 'grc': 'grc', 'gre': 'el', 'ell': 'el', 'dut': 'nl', 'nld': 'nl'}
LINK_CSS = '\n/* accessibility: links distinguishable from surrounding text (WCAG 1.4.1) */\n' \
           'html body a[href] { text-decoration: underline !important; }\n'

def _local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else None

def norm_lang(v):
    v = (v or '').strip()
    base, sep, rest = v.partition('-')
    return LANG3.get(base.lower(), base) + (sep + rest if sep else '')

# ---------- colour contrast (only mid-greys that are plainly meant for a light page)
NAMED = {'gray': '#808080', 'grey': '#808080', 'darkgray': '#a9a9a9', 'darkgrey': '#a9a9a9',
         'silver': '#c0c0c0', 'dimgray': '#696969', 'dimgrey': '#696969', 'lightslategray': '#778899',
         'slategray': '#708090'}

def _lum(rgb):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)

def _contrast_white(rgb):
    return 1.05 / (_lum(rgb) + 0.05)

def _parse_color(v):
    v = v.strip().lower()
    v = NAMED.get(v, v)
    m = re.match(r'^#([0-9a-f]{3}|[0-9a-f]{6})$', v)
    if m:
        h = m.group(1)
        if len(h) == 3: h = ''.join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r'^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$', v)
    if m:
        return tuple(min(255, int(x)) for x in m.groups())
    return None

def _darken(rgb, target=4.6):
    h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))
    while l > 0 and _contrast_white(tuple(int(round(c * 255)) for c in colorsys.hls_to_rgb(h, l, s))) < target:
        l -= 0.01
    return '#%02x%02x%02x' % tuple(int(round(c * 255)) for c in colorsys.hls_to_rgb(h, max(l, 0), s))

def fix_css_contrast(css):
    def rep(m):
        rgb = _parse_color(m.group(2))
        if rgb is None: return m.group(0)
        c = _contrast_white(rgb)
        if 2.0 <= c < 4.5:
            return m.group(1) + _darken(rgb) + m.group(3)
        return m.group(0)
    return re.sub(r'((?<![-\w])color\s*:\s*)(#[0-9a-fA-F]{3,6}|rgb\([^)]*\)|[a-zA-Z]+)(\s*(?:!important)?\s*[;}"]|\s*$)', rep, css)

def run(files, items, opfp, opf, book_title):
    base = posixpath.dirname(opfp)
    manifest = {i['path'] for i in items if i['path'] in files}
    docs = [i for i in items if i['mt'] == 'application/xhtml+xml' and i['path'] in files]
    # package language
    lang = norm_lang((re.search(r'<dc:language[^>]*>([^<]+)</dc:language>', opf) or [None, 'en'])[1])
    opf = re.sub(r'(<dc:language[^>]*>)([^<]+)(</dc:language>)', lambda m: m.group(1) + norm_lang(m.group(2)) + m.group(3), opf)
    pk = re.search(r'<package\b[^>]*>', opf).group(0)
    if 'xml:lang=' not in pk:
        opf = opf.replace(pk, pk[:-1].rstrip('/') + ' xml:lang="%s">' % lang, 1)
    trees = {}
    for d in docs:
        try:
            trees[d['path']] = etree.fromstring(files[d['path']], PARSER)
        except etree.XMLSyntaxError:
            pass
    # index of ids -> text (for labelling empty links)
    id_text = {}
    for p, root in trees.items():
        for el in root.xpath('//*[@id]'):
            t = ' '.join(''.join(el.itertext()).split())
            if t: id_text[(p, el.get('id'))] = t[:80]
    # page-list targets -> page labels (for labelling page-break markers)
    page_label = {}
    for d in docs:
        if 'nav' not in d['props'] or d['path'] not in trees: continue
        for nv in trees[d['path']].iter(H('nav')):
            if 'page-list' not in (nv.get(EPUB_T) or ''): continue
            for a in nv.iter(H('a')):
                h = a.get('href') or ''; path, _, frag = h.partition('#')
                tgt = posixpath.normpath(posixpath.join(posixpath.dirname(d['path']), unquote(path)))
                if frag: page_label[(tgt, unquote(frag))] = ' '.join(''.join(a.itertext()).split())
    stats = dict(roles=0, alts=0, labels=0)
    css_linked = set()
    for d in docs:
        p = d['path']; root = trees.get(p)
        if root is None: continue
        ch = False
        XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
        for k in ('lang', XML_LANG):
            if root.get(k) and norm_lang(root.get(k)) != root.get(k):
                root.set(k, norm_lang(root.get(k))); ch = True
        is_nav = 'nav' in d['props']
        for el in root.iter():
            n = _local(el)
            if n is None: continue
            # 1. epub:type -> matching DPUB-ARIA role where allowed
            et = el.get(EPUB_T)
            if et and not el.get('role') and n not in ('body', 'html', 'head'):
                for tok in et.split():
                    r = ROLE.get(tok)
                    if not r: continue
                    if n == 'img' and r != 'doc-cover': continue
                    if n in ANY_ROLE and r not in ('doc-cover',) or r in ALLOWED.get(n, ()):
                        if r == 'doc-noteref' or r == 'doc-backlink' or r == 'doc-biblioref' or r == 'doc-glossref':
                            if n != 'a' or el.get('href') is None: continue
                        el.set('role', r); stats['roles'] += 1; ch = True
                    break
            # 1b. page-break markers: page-list targets and epub:type=pagebreak
            eid = el.get('id')
            if eid and (p, eid) in page_label or 'pagebreak' in (et or '').split():
                if n in ('span', 'div', 'hr') or (n == 'a' and el.get('href') is None):
                    if 'pagebreak' not in (et or '').split():
                        el.set(EPUB_T, ((et or '') + ' pagebreak').strip()); ch = True
                    if el.get('role') != 'doc-pagebreak':
                        el.set('role', 'doc-pagebreak'); ch = True
                    lbl = page_label.get((p, eid)) or re.sub(r'^(page|pg|p)[_-]?', '', eid or '', flags=re.I)
                    if lbl and not el.get('aria-label') and not ''.join(el.itertext()).strip():
                        el.set('aria-label', lbl); ch = True
            # 2. empty headings: hide from assistive tech (no visual change)
            if n in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') and not ''.join(el.itertext()).strip() \
                    and not el.xpath('.//*[local-name()="img"][@alt!=""]') and el.get('aria-hidden') is None:
                el.set('aria-hidden', 'true'); ch = True
            # 3. empty table headers -> data cells
            if n == 'th' and not ''.join(el.itertext()).replace('\xa0', '').strip() and not len(el):
                el.tag = H('td'); ch = True
                for at in ('scope', 'abbr'):      # header-only attributes are invalid on td
                    el.attrib.pop(at, None)
            # 4. links without an accessible name
            if n == 'a' and el.get('href') is not None and not ''.join(el.itertext()).strip() \
                    and not el.get('aria-label') and not el.xpath('.//*[local-name()="img"][@alt!=""]'):
                href = el.get('href'); path, _, frag = href.partition('#')
                tgt = posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(path))) if path else p
                label = id_text.get((tgt, unquote(frag))) if frag else None
                if not label:
                    label = 'Return to text' if re.search(r'back|ret|ref|note', (el.get('id') or '') + href, re.I) else 'Link'
                el.set('aria-label', label[:80]); stats['labels'] += 1; ch = True
            # 5. images: cover and captioned figures get an alt; others stay honestly undescribed
            if n == 'img' and el.get('alt') is None:
                cap = None
                fig = next((a for a in el.iterancestors() if _local(a) == 'figure'), None)
                if fig is not None:
                    fc = fig.find(H('figcaption'))
                    if fc is not None: cap = ' '.join(''.join(fc.itertext()).split())
                src = el.get('src') or ''
                if 'cover-image' in _props_for(items, posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(src)))) \
                        or re.search(r'cover', src, re.I) or 'cover' in (el.get(EPUB_T) or ''):
                    el.set('alt', 'Cover of %s' % book_title); stats['alts'] += 1; ch = True
                elif cap:
                    el.set('alt', cap[:150]); stats['alts'] += 1; ch = True
        # 6. nav landmarks need distinct labels
        if is_nav:
            names = {'toc': 'Table of Contents', 'page-list': 'Page List', 'landmarks': 'Landmarks'}
            for nv in root.iter(H('nav')):
                t = (nv.get(EPUB_T) or '').split()
                # the EPUB nav-document schema forbids aria-label on <nav>; title is allowed and accepted by Ace
                if t and nv.get('hidden') is None and not nv.get('title') and not nv.get('aria-labelledby'):
                    nv.set('title', names.get(t[0], t[0].replace('-', ' ').title())); ch = True
        # 7. link underline: stylesheet of the doc (or an inline <style>)
        sheets = []
        for ln in root.iter(H('link')):
            if 'stylesheet' in (ln.get('rel') or '') and ln.get('href'):
                sheets.append(posixpath.normpath(posixpath.join(posixpath.dirname(p), unquote(ln.get('href')))))
        css_paths = {i['path'] for i in items if i['mt'] == 'text/css'}
        sheets = [s for s in sheets if s in files and s in css_paths]
        if not is_nav:
            if sheets:
                css_linked.add(sheets[-1])
            else:
                head = root.find(H('head'))
                if head is not None and not any('WCAG 1.4.1' in (s.text or '') for s in head.iter(H('style'))):
                    st = etree.SubElement(head, H('style')); st.text = LINK_CSS; ch = True
        for st in root.iter(H('style')):
            if st.text:
                t2 = fix_css_contrast(st.text)
                if t2 != st.text: st.text = t2; ch = True
        for el in root.xpath('//*[@style]'):
            s2 = fix_css_contrast(el.get('style'))
            if s2 != el.get('style'): el.set('style', s2); ch = True
        if ch:
            files[p] = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' +
                        etree.tostring(root, encoding='unicode')).encode('utf-8')
    # page list must reference every page-break marker: (re)build it from the markers in spine order
    nav = next((d for d in docs if 'nav' in d['props'] and d['path'] in trees), None)
    if nav is not None:
        idpath = {i['id']: i['path'] for i in items}
        spine = [idpath.get(r) for r in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf)]
        marks = []
        for sp in spine:
            root = trees.get(sp)
            if root is None or sp == nav['path']: continue
            for el in root.iter():
                if isinstance(el.tag, str) and 'pagebreak' in (el.get(EPUB_T) or '').split() and el.get('id'):
                    lbl = el.get('aria-label') or el.get('title') or ' '.join(''.join(el.itertext()).split()) \
                        or page_label.get((sp, el.get('id'))) or el.get('id')
                    marks.append((sp, el.get('id'), lbl))
        nroot = trees[nav['path']]
        pl = next((nv for nv in nroot.iter(H('nav')) if 'page-list' in (nv.get(EPUB_T) or '')), None)
        listed = set(page_label)
        if marks and any((sp, i) not in listed for sp, i, _ in marks):
            if pl is not None:
                pl.getparent().remove(pl)
            body = nroot.find(H('body'))
            pl = etree.SubElement(body, H('nav')); pl.set(EPUB_T, 'page-list'); pl.set('id', 'page-list')
            pl.set('hidden', ''); pl.set('role', 'doc-pagelist')
            hh = etree.SubElement(pl, H('h2')); hh.text = 'Pages'
            ol = etree.SubElement(pl, H('ol'))
            navdir = posixpath.dirname(nav['path'])
            for sp, i, lbl in marks:
                li = etree.SubElement(ol, H('li')); a = etree.SubElement(li, H('a'))
                a.set('href', posixpath.relpath(sp, navdir or '.') + '#' + i); a.text = lbl
            files[nav['path']] = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' +
                                  etree.tostring(nroot, encoding='unicode')).encode('utf-8')
            stats['pagelist_built'] = len(marks)
    for i in items:
        if i['mt'] == 'text/css' and i['path'] in files:
            css = files[i['path']].decode('utf-8', 'replace')
            c2 = fix_css_contrast(css)
            if i['path'] in css_linked and 'WCAG 1.4.1' not in c2:
                c2 += LINK_CSS
            if c2 != css: files[i['path']] = c2.encode('utf-8')
    return opf, stats

def _props_for(items, path):
    for i in items:
        if i['path'] == path: return i['props']
    return ''
