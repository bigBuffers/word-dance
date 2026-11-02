// Minimal ambient typing for the Node built-in a test uses to read a repo document outside the Vite root
// (src/i18n/zh.test.ts pins zh.ts to docs/FRONTEND.md §8). The src tsconfig only loads "vite/client" types so
// application code never leans on Node globals; this shim is for vitest (node) only.
declare module 'node:fs' {
  export function readFileSync(path: string | URL, encoding: 'utf8'): string;
}

declare const process: { cwd(): string };
