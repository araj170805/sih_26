import { fileURLToPath } from "url";
import { dirname, resolve } from "path";
import { defineConfig } from "vite";
import cesium from "vite-plugin-cesium";

const rootDir = dirname(fileURLToPath(import.meta.url));

// Multi-page app:
//   index.html    -> public landing page
//   login.html    -> authentication
//   register.html -> account creation
//   app.html      -> mission control dashboard (CesiumJS)
//   system.html   -> system health & metrics (ADMIN)

export default defineConfig({
  plugins: [cesium()],
  build: {
    rollupOptions: {
      input: {
        index: resolve(rootDir, "index.html"),
        login: resolve(rootDir, "login.html"),
        register: resolve(rootDir, "register.html"),
        app: resolve(rootDir, "app.html"),
        system: resolve(rootDir, "system.html"),
      },
    },
  },
});
