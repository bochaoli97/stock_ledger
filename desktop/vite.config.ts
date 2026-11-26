import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: { outDir: "out", target: "chrome140", sourcemap: true },
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
});
