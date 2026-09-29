# Auvyx Mono — website

Trang giới thiệu font Auvyx Mono (repo font: `../auvyx_mono`). Viết bằng [Astro](https://astro.build): xuất ra HTML tĩnh, gần như không có JavaScript, tốt cho SEO và tốc độ tải.

## Chạy

```sh
npm install
npm run dev       # http://localhost:4321
npm run build     # xuất ra dist/
npm run preview   # xem bản build
```

## Cập nhật font

Khi font thay đổi (sau `make auvyx` trong repo `auvyx_mono`):

```sh
pip install fonttools brotli pillow freetype-py uharfbuzz
python3 scripts/sync_font.py ../auvyx_mono
```

Script sẽ copy webfont, tạo lại file tải về `public/download/AuvyxMono.zip`, bảng ký tự `src/data/glyphs.json` và ảnh chia sẻ `public/og.png`.

## Trước khi deploy

- Đổi `url` trong `src/config.ts` và dòng `Sitemap:` trong `public/robots.txt` thành domain thật.
- Điền link GitHub vào `repo` trong `src/config.ts`.
- Deploy thư mục `dist/` lên Cloudflare Pages, Netlify, Vercel hoặc GitHub Pages (build command: `npm run build`, output: `dist`).

## Cấu trúc

```
src/
  config.ts            thông tin trang (tên, mô tả SEO, domain)
  layouts/Base.astro   <head>: meta SEO, Open Graph, JSON-LD, theme sáng/tối
  components/          từng section của trang
  lib/highlight.ts     tô màu code lúc build
  data/glyphs.json     danh sách ký tự (tạo bởi scripts/sync_font.py)
public/
  fonts/               webfont variable (woff2)
  download/            file zip tải về
  og.png, favicon.svg, robots.txt
```

Mã nguồn trang web: MIT. Font: SIL Open Font License 1.1.

## Video giới thiệu

`video/auvyx-mono-intro.mp4` — 1920×1080, 30fps, 56 giây, nhạc "Horizons" (Corporate Music Zone, CC BY 4.0, file trong `video/music/`). Khi đăng video phải ghi công theo `video/DESCRIPTION.md`. Các cảnh được đặt theo ô nhịp 2 giây của nhạc (120 BPM), beat vào đúng lúc hiện "Designed for code.". Thêm `--no-music` để xuất bản không nhạc. Dựng lại sau khi đổi font:

```sh
pip install numpy pillow fonttools freetype-py uharfbuzz   # cần thêm ffmpeg
python3 video/intro.py --fonts ../auvyx_mono/fonts/AuvyxMono/variable --out video/auvyx-mono-intro.mp4
python3 video/intro.py --fonts ../auvyx_mono/fonts/AuvyxMono/variable --out video/frame --preview 3 20 36   # xem thử vài khung hình
```

Kịch bản và câu chữ nằm trong `video/intro.py` (mỗi cảnh là một hàm `s_*`).
