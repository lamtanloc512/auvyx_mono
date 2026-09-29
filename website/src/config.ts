// Vercel deploy website/ tại gốc domain; GitHub Pages dùng đường dẫn repo.
const vercelHost = process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL;
const isVercel = process.env.VERCEL === "1";

export const SITE = {
  url: isVercel && vercelHost ? `https://${vercelHost}` : "https://lamtanloc512.github.io",
  base: isVercel ? "/" : "/auvyx_mono/",
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
