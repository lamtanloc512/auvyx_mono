# Contributing to Auvyx Mono

Thanks for your interest in improving Auvyx Mono!

## Issues

Search [existing issues](https://github.com/lamtanloc512/auvyx_mono/issues) first, then use one of the templates to report a rendering problem or
suggest an improvement. Screenshots with the exact text, size, app and OS help a lot.

## Changes

1. Install Python 3 with `fonttools pyyaml uharfbuzz numpy freetype-py` (and `brotli` for WOFF2).
2. Most Auvyx changes are declared in `sources/auvyx.yaml` — edit it and run `make auvyx`.
3. Glyph drawing changes that belong to the base design go into `sources/Lilex/*.glyphs`
   (edit with Glyphs/Fontra, then `make configure && make auvyx-build`).
4. Check the result (`make auvyx-install`, or preview with `make website-fonts && make website-serve`).
5. Add a line to `CHANGELOG.md` and open a pull request.

By contributing you agree that your work is released under the SIL Open Font License 1.1.
