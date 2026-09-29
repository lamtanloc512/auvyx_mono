# Auvyx Mono — website

Trang giới thiệu font Auvyx Mono (nằm trong thư mục `website/` của repo font). Viết bằng [Astro](https://astro.build): xuất ra HTML tĩnh, gần như không có JavaScript, tốt cho SEO và tốc độ tải.

## Chạy

```sh
npm install
npm run dev       # http://localhost:4321
npm run build     # xuất ra dist/
npm run preview   # xem bản build
```

## Cập nhật font

Khi font thay đổi (sau `make auvyx` ở thư mục gốc repo):

```sh
pip install fonttools brotli pillow freetype-py uharfbuzz
python3 scripts/sync_font.py ..
```

Script sẽ copy webfont, tạo lại file tải về `public/download/AuvyxMono.zip`, bảng ký tự `src/data/glyphs.json` và ảnh chia sẻ `public/og.png`.

## Deploy

Vercel: import repo, chọn Root Directory là `website`, dùng framework preset Astro và lệnh build `npm run build` (output `dist`). Vercel tự đặt `VERCEL=1`, trang sẽ dùng đường dẫn gốc `/` cho CSS, JS, font và file tải về. `VERCEL_PROJECT_PRODUCTION_URL` được dùng cho canonical URL, Open Graph và sitemap; nếu chưa có thì dùng `VERCEL_URL`. Nếu dùng domain riêng, cấu hình domain production trong Vercel.

GitHub Pages: workflow `.github/workflows/ci.yaml` build font và trang khi push lên `main`, rồi deploy tại https://lamtanloc512.github.io/auvyx_mono/. Repo cần bật Pages và gói GitHub phải hỗ trợ Pages cho repo đó.

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
  og.png, favicon.svg
```

Mã nguồn trang web: MIT. Font: SIL Open Font License 1.1.

## Video giới thiệu

`video/auvyx-mono-intro.mp4` — 1920×1080, 30fps, ~60 giây (không commit vào git vì nặng; tạo lại bằng lệnh dưới).
Nhạc: "In the Remains of the Day" (Ethereal 88, CC BY 4.0, 140 BPM) — khi đăng phải ghi công theo `video/DESCRIPTION.md`.

Kịch bản (mọi thay đổi trên hình rơi đúng một nốt nhạc có thật):

1. **Giải phẫu** — chữ "a" dựng từ đường cong Bézier (điểm neo, tay nắm), camera cận cảnh bám đầu bút rồi lùi ra
2. **Tên** — "Auvyx Mono" gõ từng chữ, đậm dần · **Tagline** từng từ
3. **Độ đậm** — "Aa" nhảy nấc Thin → Bold; ô nhịp cuối camera lao vào nét chữ → trắng xoá đúng lúc beat vào
4. **Montage** — cắt theo nốt, nhanh dần, nhiều bố cục (chữ khổng lồ, cắt cận, lưới, bậc độ đậm, ligature, dòng chữ chạy)
5. **Code**, **Tiếng Việt**, montage dồn dập, **bão glyph** đầy màn hình
6. **Fermata** — nốt dừng ngân trong tiếng vang; bão glyph nổ tung như quay chậm, chữ "a" mờ dần theo tiếng ngân
7. **Hạ màn** — piano chậm dần (ritardando); "Auvyx Mono" hiện từng chữ theo từng nốt

```sh
pip install numpy pillow fonttools freetype-py uharfbuzz   # cần thêm ffmpeg
python3 video/intro.py --fonts ../fonts/AuvyxMono/variable --out video/auvyx-mono-intro.mp4
python3 video/intro.py --fonts ../fonts/AuvyxMono/variable --out video/frame --preview 3 20.5 48.6
```

Các file: `video/music.py` (dựng nhạc, reverb, ritardando, tìm nốt), `video/intro.py` (kịch bản), `video/outline.py` (vẽ đường cong glyph), `video/fx.py` (camera, bloom, grain, vignette), `video/engine.py` (vẽ chữ).
