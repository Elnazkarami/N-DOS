# The N-DOS interface

The page `ndos gui` serves. It is a plain React single-page app: no server, no
server rendering, no data loading to hydrate. Everything it shows, it asks the
local Python server for.

## Why it ships built

`ndos_gui_static/` holds a build of this directory, committed. That is what
lets `pip install ndos` be the whole install on a lab machine with no Node and
no network — and what keeps the zero-dependency promise, since nothing here
becomes a runtime dependency of the package.

The price is that the shipped build can fall behind these sources invisibly:
the bundle is unreadable and its filenames are hashes, so an interface a
version out of date looks exactly like a current one. So the build records
what it was built from, in `ndos_gui_static/BUILD.json`, and a test fails when
the two diverge. The test needs no Node, so it runs everywhere the suite does.

## Changing it

```bash
npm ci
npx tsc --noEmit     # vite build does not typecheck; this does
```

For the dev server to be any use it needs the Python server behind it — on its
own the page can neither read a disk nor prove it may. Start one, take the
token out of the URL it prints, and hand it over:

```bash
python3 ../ndos.py gui --no-browser
# N-DOS is running at http://127.0.0.1:7373/?token=...

NDOS_TOKEN=<that token> npm run dev
```

`/api` is proxied to port 7373 (`NDOS_PORT` to change it) and the token is
injected the way the Python server injects it into the built page. Without
`NDOS_TOKEN` the page still loads and renders; it reports that it is not being
served by N-DOS, which is true.

Then put the change into the package, which is the step nothing can do for you:

```bash
python3 ../scripts/vendor_gui.py
```

That builds, copies the result into `ndos_gui_static/`, and records the
fingerprint. Commit the built files along with your source change.

## Field definitions are generated

`src/lib/ndos-generated.ts` is written by `scripts/generate_gui_fields.py` from
the vocabularies in `ndos_table.py`. Do not edit it.

It is generated because the hand-written copy it replaced had drifted: this
interface offered `male` and `female` where the standard says `F` and `M`, and
had no way to record a lesion at all. A lab doing lesion studies could not
enter one. After changing a vocabulary in Python:

```bash
python3 ../scripts/generate_gui_fields.py
```

## What each page asks the server for

| Page | Endpoints |
| --- | --- |
| This machine | `browse`, `estimate`, `scan` + `job`, `validate` |
| Manifest | `browse` (with a `.json` suffix), `open` |
| Query | `browse`, `query` — which links the project in memory first |
| Validate | `browse`, `check` |

Every one of them is read-only. `link` and `query` build a project's linked
records in memory rather than writing the file `ndos table check --emit`
produces, so querying a project leaves it exactly as it was.

## What it may not do

It may not reach the network. A lab machine need not have one, and the data
this touches is not ours to send anywhere. No fonts, no analytics, no CDN —
everything is in the bundle. A test asserts the served page contains no
absolute URL at all.

It also may not reimplement the standard. Anything that decides what the rules
*are* belongs in the Python modules, where the command line and this page both
reach the same answer. This directory renders; it does not adjudicate.
