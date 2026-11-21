/** Raster exports for the Yuanxu identity. Pass an existing sharp module via --sharp-module. */
import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const moduleIndex = process.argv.indexOf('--sharp-module');
const sharp = require(moduleIndex >= 0 ? process.argv[moduleIndex + 1] : 'sharp');
const candidateRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const isRepository = existsSync(resolve(candidateRoot, 'web')) && existsSync(resolve(candidateRoot, 'docs'));
const root = isRepository ? candidateRoot : process.cwd();
const outputIndex = process.argv.indexOf('--out');
const output = outputIndex >= 0 ? resolve(process.argv[outputIndex + 1])
  : isRepository ? resolve(root, 'web/public/brand/yuanxu') : root;
const evidenceIndex = process.argv.indexOf('--evidence');
const evidence = evidenceIndex >= 0 ? resolve(process.argv[evidenceIndex + 1])
  : isRepository ? resolve(root, 'artifacts/rebrand/final') : resolve(output, 'proofs');
await mkdir(evidence, { recursive: true });

const exports = [
  ['mark.svg', 'mark-256.png', 256],
  ['mark.svg', 'mark-512.png', 512],
  ['mark-white.svg', 'mark-white-512.png', 512],
  ['logo.svg', 'logo@2x.png', 368],
  ['logo-inverse.svg', 'logo-inverse@2x.png', 368],
  ['logo-white.svg', 'logo-white@2x.png', 368],
  ['logo-en.svg', 'logo-en@2x.png', 544],
  ['app-icon.svg', 'app-icon-1024.png', 1024],
  ['app-icon-light.svg', 'app-icon-light-1024.png', 1024],
  ['app-icon.svg', 'icon-192.png', 192],
  ['app-icon.svg', 'icon-512.png', 512],
  ['app-icon-maskable.svg', 'icon-maskable-512.png', 512],
  ['app-icon.svg', 'apple-touch-icon.png', 180],
  ['brand-overview.svg', 'brand-overview.png', 1600],
  ['social-card.svg', 'social-card.png', 1200],
];

const assets = JSON.parse(await readFile(resolve(output, 'assets.json'), 'utf8'));
for (const [input, filename, width] of exports) {
  const result = await sharp(resolve(output, input), { density: 192 })
    .resize({ width })
    .png({ compressionLevel: 9 })
    .toFile(resolve(output, filename));
  assets.push({ file: filename, width: result.width, height: result.height, label: filename });
}

// A platform-neutral legacy favicon has its own dark square, for light and dark tab bars.
const smallShape = '<path fill="#f6f7f8" d="M1 1H15V4H4V8H1ZM8 7H15V15H12V10H8Z"/>'
  + '<path fill="#f09a77" d="M1 12H8V15H1Z"/>';
for (const size of [16, 32, 48]) {
  await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><path fill="#20262e" d="M0 0H16V16H0Z"/>${smallShape}</svg>`), { density: 288 })
    .resize(size, size).png().toFile(resolve(output, `favicon-${size}.png`));
  assets.push({ file: `favicon-${size}.png`, width: size, height: size, label: `标签页图标 ${size}px` });
}

// PNG-backed multi-resolution ICO: no additional codec or app dependency.
const iconSizes = [16, 32, 48];
const iconImages = await Promise.all(iconSizes.map(size => readFile(resolve(output, `favicon-${size}.png`))));
const icoHeader = Buffer.alloc(6 + iconImages.length * 16);
icoHeader.writeUInt16LE(1, 2);
icoHeader.writeUInt16LE(iconImages.length, 4);
let iconOffset = icoHeader.length;
for (let i = 0; i < iconImages.length; i++) {
  const entry = 6 + i * 16;
  icoHeader[entry] = iconSizes[i];
  icoHeader[entry + 1] = iconSizes[i];
  icoHeader.writeUInt16LE(1, entry + 4);
  icoHeader.writeUInt16LE(32, entry + 6);
  icoHeader.writeUInt32LE(iconImages[i].length, entry + 8);
  icoHeader.writeUInt32LE(iconOffset, entry + 12);
  iconOffset += iconImages[i].length;
}
await writeFile(resolve(output, 'favicon.ico'), Buffer.concat([icoHeader, ...iconImages]));
assets.push({ file: 'favicon.ico', sizes: iconSizes, label: '多尺寸标签页图标' });
await writeFile(resolve(output, 'assets.json'), JSON.stringify(assets, null, 2) + '\n');

// Real-size and enlarged proofs use the same exported files a consumer receives.
const imageUri = async name => `data:image/png;base64,${(await readFile(resolve(output, name))).toString('base64')}`;
const markUri = `data:image/svg+xml;base64,${(await readFile(resolve(output, 'mark.svg'))).toString('base64')}`;
const monoUri = `data:image/svg+xml;base64,${(await readFile(resolve(output, 'mark-ink.svg'))).toString('base64')}`;
const inverseUri = `data:image/svg+xml;base64,${(await readFile(resolve(output, 'mark-inverse.svg'))).toString('base64')}`;
let proof = '<rect width="1200" height="360" fill="#f6f7f8"/><rect x="600" width="600" height="360" fill="#20262e"/>';
for (const [i, size] of [16, 24, 32, 48, 64, 96].entries()) {
  const x = 24 + i * 96;
  proof += `<image href="${markUri}" x="${x}" y="40" width="${size}" height="${size}"/>`;
  proof += `<image href="${monoUri}" x="${x}" y="180" width="${size}" height="${size}"/>`;
  proof += `<image href="${inverseUri}" x="${600 + x}" y="40" width="${size}" height="${size}"/>`;
}
for (const [i, size] of iconSizes.entries()) {
  proof += `<image href="${await imageUri(`favicon-${size}.png`)}" x="${632 + i * 96}" y="180" width="${size}" height="${size}"/>`;
}
await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="360" viewBox="0 0 1200 360">${proof}</svg>`))
  .png().toFile(resolve(evidence, 'small-size-proof.png'));
await sharp(resolve(evidence, 'small-size-proof.png')).resize(2400, 720, { kernel: 'nearest' })
  .png().toFile(resolve(evidence, 'small-size-proof-2x.png'));
await sharp(resolve(output, 'brand-overview.svg'), { density: 144 }).resize(3200, 2120)
  .png().toFile(resolve(evidence, 'brand-overview-2x.png'));

// Unlabelled optical proof: 24px and 72px rows, repeated on light and dark surfaces.
const functionalIcons = ['knowledge', 'governance', 'retrieval', 'citation', 'evaluation', 'trace'];
let iconProof = '<rect width="720" height="400" fill="#f6f7f8"/><rect y="200" width="720" height="200" fill="#20262e"/>';
for (const [i, name] of functionalIcons.entries()) {
  const source = await readFile(resolve(output, `icons/${name}.svg`), 'utf8');
  for (const [baseY, color] of [[0, '#20262e'], [200, '#f6f7f8']]) {
    const uri = `data:image/svg+xml;base64,${Buffer.from(source.replaceAll('currentColor', color)).toString('base64')}`;
    for (const [size, y] of [[24, 40], [72, 96]]) {
      iconProof += `<image href="${uri}" x="${60 + i * 120 - size / 2}" y="${baseY + y}" width="${size}" height="${size}"/>`;
    }
  }
}
await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="720" height="400" viewBox="0 0 720 400">${iconProof}</svg>`))
  .png().toFile(resolve(evidence, 'functional-icon-proof.png'));

console.log(`Exported ${exports.length + iconSizes.length} PNG files, a multi-resolution ICO and visual proofs.`);
