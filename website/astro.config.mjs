// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import { SITE } from "./src/config.ts";

export default defineConfig({
  site: SITE.url,
  integrations: [sitemap()],
  build: { inlineStylesheets: "auto" },
});
