#!/usr/bin/env node
/**
 * Lightweight repo-relative link check for handbook sources (no HTTP).
 * Usage: node scripts/docs/check_doc_links.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "../..");
const ROOTS = [
  path.join(REPO, "docs-site", "docs"),
  path.join(REPO, "docs-site", "i18n", "en", "docusaurus-plugin-content-docs", "current"),
];

const LINK_RE = /\]\(([^)]+)\)/g;

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, out);
    else if (/\.(md|mdx)$/i.test(ent.name)) out.push(p);
  }
  return out;
}

function checkFile(file) {
  const text = fs.readFileSync(file, "utf8");
  const base = path.dirname(file);
  const errors = [];
  let m;
  while ((m = LINK_RE.exec(text)) !== null) {
    let href = m[1].trim();
    if (href.startsWith("http://") || href.startsWith("https://")) continue;
    if (href.startsWith("mailto:") || href.startsWith("#")) continue;
    const noHash = href.split("#")[0];
    if (!noHash) continue;
    const target = path.normalize(path.join(base, noHash));
    if (!fs.existsSync(target)) {
      errors.push({ href, target });
    }
  }
  return errors;
}

let bad = 0;
for (const root of ROOTS) {
  for (const file of walk(root)) {
    const errs = checkFile(file);
    if (errs.length) {
      bad += errs.length;
      console.error(file);
      for (const e of errs) console.error("  missing:", e.href, "->", e.target);
    }
  }
}

if (bad) {
  console.error(`\ncheck_doc_links: ${bad} broken relative link(s)`);
  process.exit(1);
}
console.log("check_doc_links: OK");
