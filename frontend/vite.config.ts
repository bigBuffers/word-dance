// Vite 8 + Vitest 5 configuration (FRONTEND.md §1, DEPLOY.md §8).
// Dev: Vite on :5173 proxies /api and /media to the FastAPI dev server on :8000 (same-origin cookies).
// The proxy keeps the browser's Host header (changeOrigin: false) so the backend's CSRF check sees
// Origin == Host-derived origin without relying on WD_DEV.
import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const BACKEND = 'http://127.0.0.1:8000';

export default defineConfig({
  base: '/',
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
      '/media': { target: BACKEND, changeOrigin: false },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: false },
      '/media': { target: BACKEND, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    // Hashed assets live under dist/assets and are mounted immutable by FastAPI (FRONTEND §1).
    assetsDir: 'assets',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    clearMocks: true,
    restoreMocks: true,
  },
});
