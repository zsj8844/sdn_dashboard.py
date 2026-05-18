import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babelPlugin from '@rolldown/plugin-babel'

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [
    react(),
    await babelPlugin({
      presets: [reactCompilerPreset()],
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
  },
}))
