"""The N-DOS interface, already built.

These files are produced from `gui/` and committed so that installing the
package is enough: running the interface needs no Node, no npm and no build
step. Rebuild with `cd gui && npm install && npm run build`, then copy
`gui/dist/` here.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
