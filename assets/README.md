# assets

The link preview card and the site icon. Deliberately a wordmark and nothing
else: a project with no completed pilot has not earned a logo, and a card that
is only type cannot go out of date.

| File | Used for |
| --- | --- |
| `social-card.svg` | **The source.** 1280×640, the size GitHub's social preview and Open Graph both accept |
| `social-card.png` | Rendered from it — Open Graph and Twitter need a raster, and so does GitHub |
| `icon.svg` | **The source** for the browser tab icon |
| `icon.png` | Rendered from it, 192×192, for clients that will not take an SVG |

The SVGs are the source; the PNGs are derived. To regenerate them after editing
an SVG, render with any browser engine — this used headless Chrome, so that the
PNG is laid out by the same renderer the SVG is written for:

```bash
chrome --headless --disable-gpu --hide-scrollbars \
    --window-size=1280,640 --screenshot=assets/social-card.png \
    "file://$PWD/assets/social-card.svg"

chrome --headless --disable-gpu --hide-scrollbars \
    --window-size=64,64 --force-device-scale-factor=3 \
    --screenshot=assets/icon.png "file://$PWD/assets/icon.svg"
```

Then `python3 scripts/build_docs.py` to copy them onto the site.

**The one thing this cannot do for you:** GitHub's repository social preview is
set by hand, and has no API. Upload `social-card.png` at
*Settings → General → Social preview*. Until then a shared repository link
shows GitHub's generic card.
