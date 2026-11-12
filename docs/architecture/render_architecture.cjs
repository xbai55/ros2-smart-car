// SVG -> 3x PNG using sharp. Set NODE_PATH to your installed dependencies.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');
const root = __dirname;
const source = path.join(root, 'insightrover-system-architecture.svg');
(async () => {
  await sharp(source, { density: 216 }).png().toFile(path.join(root, 'insightrover-system-architecture.png'));
  await sharp(source).resize(1920,1080).png().toFile(path.join(root, 'insightrover-system-architecture-preview.png'));
  const meta = await sharp(path.join(root,'insightrover-system-architecture.png')).metadata();
  console.log(JSON.stringify({width:meta.width,height:meta.height,format:meta.format}));
})();
