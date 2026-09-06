import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// dev: base='/'  + proxy 到本地隧道后端(8095,与ssh同端口)
// build: base='/static/' 输出到 anvil/static
const isDev = process.argv.includes('--mode development') || process.env.NODE_ENV === 'development'

export default defineConfig({
  base: isDev ? '/' : '/static/',
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8095',
        changeOrigin: true,
      },
      '/admin-api': {
        target: 'http://localhost:8097',
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/admin-api/, '/api'),
      },
      '/voice-api': {
        target: 'http://localhost:8098',
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/voice-api/, ''),
      },
      '/ocr-api': {
        target: 'http://localhost:8099',
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/ocr-api/, ''),
      },
      '/draft-api': {
        target: 'http://localhost:8100',
        changeOrigin: true,
        rewrite: (p: string) => p.replace(/^\/draft-api/, ''),
      },
      '/static': {
        target: 'http://localhost:8095',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: resolve(__dirname, '../Anvil/anvil/static'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/[name].[hash].js',
        assetFileNames: 'assets/[name].[hash][extname]'
      }
    }
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  }
})
