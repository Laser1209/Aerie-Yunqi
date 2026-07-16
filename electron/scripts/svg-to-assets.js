// Build logo assets from the single source-of-truth SVG.
// Outputs:
//   builder/icon-1024.png       (1024x1024, used as Builder fallback)
//   builder/icon.ico            (multi-size ICO for EXE)
//   src/renderer/assets/logo.png (800x800, used inside the UI)
//   src/renderer/assets/logo-64.png (small chip variant)
// Plus: a 32x32 favicon for the BrowserWindow.

'use strict';

const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

const ROOT = path.resolve(__dirname, '..', '..');
const SVG = path.join(ROOT, 'Aerie · 云栖.svg');
const BUILDER = path.join(__dirname, '..', 'builder');
const RENDERER_ASSETS = path.join(__dirname, '..', 'src', 'renderer', 'assets');

function ensureDir(d) { if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true }); }

async function main() {
  if (!fs.existsSync(SVG)) {
    console.error('[FATAL] source SVG not found:', SVG);
    process.exit(1);
  }
  ensureDir(BUILDER);
  ensureDir(RENDERER_ASSETS);

  const svgBuf = fs.readFileSync(SVG);
  const baseMeta = await sharp(svgBuf).metadata().catch(() => null);
  console.log('[INFO] SVG size:', (svgBuf.length / 1024 / 1024).toFixed(2), 'MB',
              '| meta:', baseMeta && `${baseMeta.width}x${baseMeta.height}`);

  // 1024 primary
  const png1024 = path.join(BUILDER, 'icon-1024.png');
  await sharp(svgBuf).resize(1024, 1024, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png({ compressionLevel: 9 }).toFile(png1024);
  console.log('[OK] wrote', png1024);

  // 800 renderer logo
  const png800 = path.join(RENDERER_ASSETS, 'logo.png');
  await sharp(svgBuf).resize(800, 800, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png({ compressionLevel: 9 }).toFile(png800);
  console.log('[OK] wrote', png800);

  // 96 px chip
  const png96 = path.join(RENDERER_ASSETS, 'logo-96.png');
  await sharp(svgBuf).resize(96, 96, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png({ compressionLevel: 9 }).toFile(png96);
  console.log('[OK] wrote', png96);

  // 32 px favicon
  const png32 = path.join(__dirname, '..', 'src', 'renderer', 'favicon.png');
  ensureDir(path.dirname(png32));
  await sharp(svgBuf).resize(32, 32, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toFile(png32);
  console.log('[OK] wrote', png32);

  // ICO: multiple sizes for EXE / tray
  const icoSizes = [16, 24, 32, 48, 64, 128, 256];
  const pngBuffers = await Promise.all(icoSizes.map(async (sz) => {
    return await sharp(svgBuf)
      .resize(sz, sz, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png()
      .toBuffer();
  }));
  // Hand-build a multi-size ICO container with PNG payloads
  const icoPath = path.join(BUILDER, 'icon.ico');
  writeIco(icoPath, pngBuffers, icoSizes);
  console.log('[OK] wrote', icoPath, '(' + icoSizes.length + ' sizes)');
}

// Minimal multi-size PNG-in-ICO writer (Windows accepts PNG-in-ICO since Vista)
function writeIco(filePath, pngBuffers, sizes) {
  const count = pngBuffers.length;
  const header = Buffer.alloc(6 + count * 16);
  header.writeUInt16LE(0, 0);       // reserved
  header.writeUInt16LE(1, 2);       // type = icon
  header.writeUInt16LE(count, 4);   // image count
  let offset = 6 + count * 16;
  const entries = [];
  for (let i = 0; i < count; i++) {
    const sz = sizes[i] === 256 ? 0 : sizes[i];
    const start = 6 + i * 16;
    header.writeUInt8(sz, start + 0);
    header.writeUInt8(sz, start + 1);
    header.writeUInt8(0, start + 2);   // colors
    header.writeUInt8(0, start + 3);   // reserved
    header.writeUInt16LE(1, start + 4); // planes
    header.writeUInt16LE(32, start + 6); // bpp
    header.writeUInt32LE(pngBuffers[i].length, start + 8);
    header.writeUInt32LE(offset, start + 12);
    offset += pngBuffers[i].length;
    entries.push(pngBuffers[i]);
  }
  fs.writeFileSync(filePath, Buffer.concat([header, ...entries]));
}

main().catch((e) => { console.error('[FATAL]', e); process.exit(1); });
