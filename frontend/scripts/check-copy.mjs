#!/usr/bin/env node
// Enforces the i18n rules of FRONTEND.md §8 and the glossary of DESIGN §0.3 over frontend/src:
//   1. Chinese UI copy (CJK characters) may appear in *.tsx files only under src/i18n/;
//   2. the forbidden glossary synonym of the personal word bank never appears anywhere.
// Exit code 1 lists every offending `file:line`. Used by `npm run lint`; src/i18n/zh.test.ts applies
// the same rules inside `npm test`.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src', import.meta.url));
// Built from code points so this file never contains the characters it hunts for.
const CJK = new RegExp(`[${String.fromCharCode(0x4e00)}-${String.fromCharCode(0x9fa5)}]`);
const FORBIDDEN_TERM = String.fromCharCode(0x5355, 0x8bcd, 0x672c);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else out.push(path);
  }
  return out;
}

export function checkCopy(root = SRC) {
  const problems = [];
  for (const file of walk(root)) {
    const rel = relative(root, file).split(sep).join('/');
    const lines = readFileSync(file, 'utf8').split('\n');
    const copyAllowed = rel.startsWith('i18n/');
    lines.forEach((line, i) => {
      if (line.includes(FORBIDDEN_TERM)) problems.push(`${rel}:${i + 1}: forbidden glossary term (DESIGN 0.3)`);
      if (!copyAllowed && rel.endsWith('.tsx') && CJK.test(line)) problems.push(`${rel}:${i + 1}: Chinese copy outside src/i18n (FRONTEND 8)`);
    });
  }
  return problems;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const problems = checkCopy();
  if (problems.length) {
    console.error(problems.join('\n'));
    process.exit(1);
  }
  console.log('copy check OK');
}
