<p align="center">
  <img src="./images/hero.png" alt="Auvyx Mono — a monospaced typeface for code" width="720">
</p>

# Auvyx Mono

Auvyx Mono is a free, open-source monospaced typeface for code. Calm, legible and a little bit warm — with
seven weights from Thin to Bold, true italics, programming ligatures, 1,073 characters and careful Vietnamese
support. Available as static TTF/OTF, variable TTF and WOFF2.

<p align="center"><img src="./images/weights.png" alt="Seven weights, upright and italic" width="100%"></p>
<p align="center"><img src="./images/code.png" alt="Auvyx Mono in code" width="100%"></p>

## Features

- **7 weights + variable font** — `wght` 100–700, upright and italic.
- **True italics** — single-storey `a` and `g`, flowing `k l j r v w t f`, a straight quiet `x`.
- **Ligatures** — `=> != === |> :: && <= /* */ <!--` … turn them off with `calt` if you prefer.
- **Character variants** — slashed/plain/backslashed zero, double-storey `g`, high asterisk, curvier parentheses and more (`cv02 cv04 cv06 cv08–cv11 cv13–cv15 zero ss01–ss04`).
- **Languages** — Latin (incl. Vietnamese), Greek and Cyrillic; box drawing and Powerline symbols.
- **Comfortable spacing** — a slightly tighter 590-unit cell.

<p align="center"><img src="./images/specimen.png" alt="Specimen: Lorem ipsum and Vietnamese text" width="100%"></p>

## Install

Download the latest release (or build it yourself, see below), then:

- **macOS** — open `variable/`, select both `.ttf` files, double-click → *Install Font*.
- **Windows** — select both `.ttf` files in `variable/`, right-click → *Install for all users*.
- **Linux** — copy the `.ttf` files to `~/.local/share/fonts` and run `fc-cache -f`.

Editor setup, e.g. VS Code:

```json
"editor.fontFamily": "'Auvyx Mono', monospace",
"editor.fontLigatures": true
```

## Build

```sh
make auvyx            # build fonts/AuvyxMono from the prebuilt base fonts (Python + fonttools, pyyaml, uharfbuzz, numpy, freetype-py)
make auvyx-install    # install the variable fonts on macOS
make configure && make auvyx-build   # full build from the .glyphs sources
```

All Auvyx-specific changes (family name, cell width, default alternates, borrowed glyphs, weight matching) are
declared in [`sources/auvyx.yaml`](sources/auvyx.yaml) and applied by [`scripts/auvyx.py`](scripts/auvyx.py).

## Website & video

The website lives in [`website/`](website) (Astro, static, SEO-ready). The intro video is rendered from code in
[`website/video/`](website/video).

```sh
make website-configure   # npm install
make website-fonts       # copy the freshly built fonts into the site
make website-serve       # http://localhost:4321
make website-build       # → website/dist
make video               # → website/video/auvyx-mono-intro.mp4
```

## Credits & license

Auvyx Mono is released under the [SIL Open Font License 1.1](OFL.txt).

It is a modified version of [Lilex](https://github.com/mishamyrt/Lilex) by Mikhael Khrustik, itself based on
[IBM Plex Mono](https://github.com/IBM/plex). Some letters come from [Recursive](https://github.com/arrowtype/recursive)
(Arrow Type) and [Geist Mono](https://github.com/vercel/geist-font) (Vercel), both under the OFL.
See [OFL.txt](OFL.txt) and [AUTHORS](AUTHORS) for the full copyright notices.

Internal source file names (`sources/Lilex/*.glyphs`, `lilexgen`) are kept unchanged so upstream improvements
can still be merged:

```sh
git remote add upstream https://github.com/mishamyrt/Lilex   # if not already added
git fetch upstream && git merge upstream/master && make auvyx
```
