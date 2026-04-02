#!/usr/bin/env node
/**
 * Mirror default-locale docs into i18n/en so `locales: ['zh-Hans','en']` builds.
 * English overrides: docs-site/i18n/en-overrides/current/** (same paths as under docs/)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "../..");
const DOCS = path.join(REPO, "docs-site", "docs");
const TARGET = path.join(REPO, "docs-site", "i18n", "en", "docusaurus-plugin-content-docs", "current");
const OVERRIDES = path.join(REPO, "docs-site", "i18n", "en-overrides", "current");

function rmrf(p) {
  if (fs.existsSync(p)) fs.rmSync(p, { recursive: true, force: true });
}

function copyRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, ent.name);
    const d = path.join(dest, ent.name);
    if (ent.isDirectory()) copyRecursive(s, d);
    else fs.copyFileSync(s, d);
  }
}

rmrf(TARGET);
copyRecursive(DOCS, TARGET);

if (fs.existsSync(OVERRIDES)) {
  copyRecursive(OVERRIDES, TARGET);
}

console.log("sync-handbook-i18n:", TARGET);
