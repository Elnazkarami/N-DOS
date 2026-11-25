# site

The website, written rather than themed.

GitHub Pages offers a handful of themes, and a site using one is recognisable
as that theme at a glance. A project asking laboratories to adopt its standard
should not look like it was assembled from the first option offered — so there
is no theme here, and these four things replace it.

| File | What it is |
| --- | --- |
| `layout.html` | The page shell: masthead, content, contents panel, colophon |
| `style.css` | All of the styling. No framework, no build step |
| `toc.js` | Builds the contents panel from the headings already on the page |
| `fonts/` | IBM Plex, served from this site |

`scripts/build_docs.py` copies these into `docs/` and fills the `<!--NAV-->`
marker in the layout from the `NAV` table in that script, so the navigation
has one definition rather than two.

## Three decisions

**Type.** IBM Plex: serif for prose because this is a document, sans for
structure, mono for anything a terminal printed. Served from this site rather
than from a font CDN, which would hand every visitor's address to a third
party on a site whose whole claim is that nothing leaves your machine. Seven
weight files, about 145 KB in total, and a licence
([OFL](fonts/OFL.txt)) that travels with them.

**Dark bands.** The masthead, the colophon and every code block share the
colour of the link preview card in `../assets/`, so the pieces look like one
project rather than several.

**One accent.** Everything else is ink on paper. Colour marks what you can act
on and nothing else, which is how it keeps meaning something.

## Changing it

Edit the file here, then rebuild and look at it:

```bash
python3 scripts/build_docs.py
python3 -m unittest discover -s tests -p test_docs.py
```

The tests will tell you if the stylesheet asks for a font that is not
published, if a page is missing from the masthead, if the site has acquired a
theme, or if `docs/` no longer matches what these files produce. They cannot
tell you whether it looks right, so open it.
