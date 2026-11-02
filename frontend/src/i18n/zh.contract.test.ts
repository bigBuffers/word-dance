/// <reference types="node" />
// FRONTEND.md §8 is "binding" and zh.ts declares itself "FRONTEND.md §8 verbatim" (TASKS P0 step 8). This test keeps
// the two tables identical — same keys, same strings, same formatter functions — so a copy change lands in both files
// in one commit. The integration review found three zh.ts keys that §8 lacked (common.backToToday, word.speak,
// word.speechUnsupported); API.md's rule "update the contract and the code in one commit" applies here too.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { zh } from './zh';

// fileURLToPath(string): under jsdom `new URL()` yields jsdom's URL class, which Node's fileURLToPath rejects.
const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND_MD = resolve(HERE, '../../../docs/FRONTEND.md');
const ZH_TS = resolve(HERE, 'zh.ts');

type Leaf = string | ((...args: never[]) => string);

/** The `export const zh = { … } as const;` block of FRONTEND.md §8. */
function section8Source(): string {
  const md = readFileSync(FRONTEND_MD, 'utf8');
  const start = md.indexOf('## 8. i18n strings');
  const fence = md.indexOf('```ts\n', start);
  const end = md.indexOf('\n```', fence + 6);
  if (start < 0 || fence < 0 || end < 0) throw new Error('FRONTEND.md §8 code block not found');
  return md.slice(fence + 6, end);
}

/** Evaluate a TypeScript module that exports `zh` (types erased by tsc, same printer for both sides). */
function evaluate(source: string): Record<string, unknown> {
  const js = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText;
  const body = js.replace(/^export\s+const\s+zh\b/m, 'const zh').replace(/^export\s+.*$/gm, '');
  const factory = new Function(`${body}\nreturn zh;`) as () => Record<string, unknown>;
  return factory();
}

function flatten(node: unknown, prefix = '', out = new Map<string, Leaf>()): Map<string, Leaf> {
  if (typeof node === 'string' || typeof node === 'function') {
    out.set(prefix, node as Leaf);
  } else if (node && typeof node === 'object') {
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      flatten(value, prefix ? `${prefix}.${key}` : key, out);
    }
  } else {
    throw new Error(`unexpected leaf at ${prefix}: ${String(node)}`);
  }
  return out;
}

const normalise = (leaf: Leaf): string => (typeof leaf === 'string' ? JSON.stringify(leaf) : leaf.toString().replace(/\s+/g, ' ').trim());

let cache: { doc: Map<string, Leaf>; code: Map<string, Leaf> } | null = null;
function tables(): { doc: Map<string, Leaf>; code: Map<string, Leaf> } {
  cache ??= { doc: flatten(evaluate(section8Source())), code: flatten(evaluate(readFileSync(ZH_TS, 'utf8'))) };
  return cache;
}

describe('FRONTEND.md §8 ↔ zh.ts', () => {
  it('evaluates zh.ts to the table Vite ships', () => {
    expect([...tables().code.keys()]).toEqual([...flatten(zh).keys()]);
    expect(tables().code.size).toBeGreaterThan(300);
  });

  it('has the same keys in the document and in the code', () => {
    const { doc, code } = tables();
    expect({
      inCodeOnly: [...code.keys()].filter((k) => !doc.has(k)),
      inDocOnly: [...doc.keys()].filter((k) => !code.has(k)),
    }).toEqual({ inCodeOnly: [], inDocOnly: [] });
  });

  it('has identical values (strings and formatter functions)', () => {
    const { doc, code } = tables();
    const differing: string[] = [];
    for (const [key, leaf] of code) {
      const other = doc.get(key);
      if (other !== undefined && normalise(other) !== normalise(leaf)) differing.push(`${key}: §8 ${normalise(other)} ≠ zh.ts ${normalise(leaf)}`);
    }
    expect(differing).toEqual([]);
  });
});
