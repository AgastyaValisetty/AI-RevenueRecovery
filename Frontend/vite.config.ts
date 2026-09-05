import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// VITE_API_TARGET lets docker compose point the proxy at the docker DNS name
// (http://people_service:8000) while `npm run dev` on the host still defaults
// to http://localhost:8000.
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
