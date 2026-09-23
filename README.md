# epub3-pipeline

Converts EPUB 2 books to modern, validated EPUB 3 and brings existing EPUB 3 books up to the same standard. The pipeline wraps Kevin Hendricks' **ePub3-itizer** Sigil plugin with the repairs Sigil does when it opens a book, a clean-up pass for the HTML and packaging, and accessibility fixes driven by **Ace by DAISY**.

First used on `~/Downloads/Bulk Books`, 23 Sep 2026: 264 of 264 books came out as EPUB 3.4 with 0 epubcheck errors.

## Requirements

- **Sigil** (`brew install --cask sigil`). The pipeline runs the plugin through Sigil's own plugin launcher and bundled Python 3.14, which provides lxml, gumbo and css_parser.
- **epubcheck** (`brew install epubcheck`, which also pulls in OpenJDK)
- **Ace by DAISY**, only needed for `./epub3 ace` (`npm install -g @daisy/ace --allow-scripts=puppeteer`)

## Usage

```bash
./epub3 run   ~/path/to/Library --dry     # convert + validate into work/, change nothing
./epub3 run   ~/path/to/Library           # convert and replace books that pass the gate
./epub3 run   ~/path/to/Library "Some Book.epub"   # only this book (path relative to the library)
./epub3 audit ~/path/to/Library           # epubcheck every book -> work/<library>/audit.json
./epub3 ace   ~/path/to/Library           # Ace scan -> work/<library>/ace/*/report.html
```

A book is **replaced only if** epubcheck shows no new error types **and** the visible text of every document is unchanged. The text check is by content, so it still works after files are renamed. EPUB 2 originals go to `~/.Trash/<Library> EPUB2 originals/`. Each book's result goes to `work/<Library>/run.jsonl`. A re-run skips books already in the log, so an interrupted run can be resumed.

## Pipeline

| Stage | File | What it does |
|---|---|---|
| Pre (Sigil on-load) | `fixes.pre` | Normalizes the OPF: `opf:` and `p6:` prefixes, `xmlns=""`, an empty unique identifier, manifest entries whose file is missing, a stale `nav.xhtml`, duplicate manifest and spine entries. Generates a missing NCX from the spine. Makes IDs valid XML names. Renames files to URL-safe names and updates every reference. Mends malformed XHTML with Sigil's gumbo parser. |
| Convert | `convert.py` + `plugins/ePub3-itizer` | Runs the plugin unchanged, headless through Sigil's `launcher.py`. Only its Qt "Save as" dialog is replaced, by `stubs/PySide6`. |
| Post | `fixes.post` | Takes the nav out of the spine. Repairs NCX `playOrder` and IDs. Declares the cover image from the cover page if none is marked. |
| Modernize | `modernize.py` | Converts presentational HTML (`cellspacing`, `align`, `valign`, `<font>`, `<center>`, `<big>`, `<tt>` and so on) to CSS. Sets `lang`/`xml:lang`. Makes IDs unique. Strips MS Word, Kindle and Adobe debris. Fills empty `<title>`s. Adds `toc`/`bodymatter` landmarks. Writes EPUB Accessibility 1.1 metadata. |
| Hygiene | `hygiene.py` | Fixes the HTML5 content model (block inside phrasing, list and table children, `<col>`), links to missing targets, dangling fragments, dead fonts and images, CSS syntax (re-serialized with css_parser only when it fails to parse), guide/spine/NCX consistency. |
| Accessibility | `a11y.py` | Adds the package `xml:lang`, DPUB-ARIA roles matching `epub:type` (only where HTML allows them), labelled page-break markers, and a page list built from those markers. Labels links with no text and names visible navs. Hides empty headings. Underlines links (WCAG 1.4.1). Darkens mid-grey text below 4.5:1. Adds alt text for covers and captioned figures. |
| Gate | `run.py`, `check.py` | epubcheck before and after, plus a text-fidelity comparison. |

## Deliberately not automated

- **Image descriptions.** Images other than covers and captioned figures keep no `alt`, and the accessibility metadata says so honestly: no `alternativeText` claim, `accessModeSufficient` set to `textual,visual`, and the summary counts undescribed images.
- **No WCAG conformance claim** (`dcterms:conformsTo`), because no audit was done.
- **Heading levels, TOC order** (NAV-011 / `epub-toc-order`) and **`pageBreakSource`** stay as the publisher left them. The print ISBN isn't in the files.

## Upstream

`plugins/ePub3-itizer` is v0.6.0, taken unchanged from https://github.com/kevinhendricks/ePub3-itizer at commit `2d4f58d` (LGPL 2.1, see `COPYING.txt`).
