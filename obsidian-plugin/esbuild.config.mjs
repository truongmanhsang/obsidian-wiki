import esbuild from "esbuild";
import { readFile } from "node:fs/promises";

const production = process.argv[2] === "production";
const manifest = JSON.parse(await readFile(new URL("./manifest.json", import.meta.url)));

await esbuild.build({
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian", "electron", "@codemirror/*", "codemirror", "moment"],
  format: "cjs",
  platform: "browser",
  target: "es2020",
  sourcemap: production ? false : "inline",
  minify: production,
  outfile: "main.js",
  logLevel: "info",
});

console.log(`Built ${manifest.id} ${manifest.version}`);
