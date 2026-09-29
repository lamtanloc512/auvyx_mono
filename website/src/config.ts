// Thông tin chung của trang (canonical URL, Open Graph, sitemap).
// Mặc định deploy lên GitHub Pages: https://lamtanloc512.github.io/auvyx_mono/
// Nếu dùng domain riêng: đặt url = "https://domain-cua-ban", base = "/".
export const SITE = {
  url: "https://lamtanloc512.github.io",
  base: "/auvyx_mono/",
  name: "Auvyx Mono",
  title: "Auvyx Mono — a monospaced typeface for code",
  description:
    "Auvyx Mono is a free, open-source monospaced font for developers. Seven weights from Thin to Bold, true italics, programming ligatures, full Vietnamese support, and a variable font. Licensed under the SIL Open Font License.",
  author: "Ethan Lam",
  repo: "https://github.com/lamtanloc512/auvyx_mono",
  download: "",
  version: "1.0",
};
SITE.download = SITE.base + "download/AuvyxMono.zip";

/** Đường dẫn trong trang, có tính base path (vd: withBase("fonts/x.woff2") → "/auvyx_mono/fonts/x.woff2"). */
export const withBase = (p = "") => SITE.base + p.replace(/^\//, "");
