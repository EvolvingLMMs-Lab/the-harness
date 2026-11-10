/** Assemble the approved homepage, in English at / and Chinese at /zh-cn/, alongside the generated Starlight docs. */
const source = new URL('../../design/site-preview/web/', import.meta.url);
const output = new URL('../dist/', import.meta.url);
const files = [
  'index.html', 'app.js', 'demos.js', 'demo-player.js', 'logos.js', 'LOGOS-LICENSE.md', 'style.css', 'home.css', 'archive.css', 'archive-banner.js',
  'home-figures.js', 'cyberspace.js', 'logo-motion.js', 'animation/lmms-pixelfont.js', 'animation/lmms-logo-cyber.js',
  'figures/harness.js', 'figures/hairline-kernel.js', 'figures/HAIRLINE-LICENSE',
  'vendor/three.module.js', 'vendor/three.core.js', 'vendor/THREE-LICENSE.txt',
  'assets/logo-neon.png', 'assets/home/computer.webp', 'assets/home/terminal.webp',
];
for (const entry of Deno.readDirSync(new URL('archive-fonts/', source))) {
  if (entry.isFile && entry.name.endsWith('.ttf')) files.push(`archive-fonts/${entry.name}`);
}
for (const entry of Deno.readDirSync(new URL('assets/demos/', source))) {
  if (entry.isFile) files.push(`assets/demos/${entry.name}`);
}
for (const file of files) {
  const target = new URL(file, output);
  await Deno.mkdir(new URL('./', target), { recursive: true });
  await Deno.copyFile(new URL(file, source), target);
}

// The same page serves Chinese: app.js picks its strings from the path and <html lang>.
const english = await Deno.readTextFile(new URL('index.html', source));
const chinese = english
  .replace('<html lang="en">', '<html lang="zh-CN">')
  .replace(/<meta name="description" content="[^"]*">/, '<meta name="description" content="The Harness：自动化控制，适用于一切能行动的东西。">')
  .replace(/<title>[^<]*<\/title>/, '<title>The Harness — LMMS Lab</title>');
if (chinese === english || !chinese.includes('lang="zh-CN"')) throw new Error('index.html changed shape; update the Chinese homepage rewrite');
await Deno.mkdir(new URL('zh-cn/', output), { recursive: true });
await Deno.writeTextFile(new URL('zh-cn/index.html', output), chinese);
console.log(`Homepage: copied ${files.length} assets to dist/, Chinese page at dist/zh-cn/`);
