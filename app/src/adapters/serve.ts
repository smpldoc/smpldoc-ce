// Container entry point: node src/adapters/serve.ts
import { startApp } from "./main.ts";
import { ConfigError } from "../app/config.ts";

try {
  const app = await startApp(process.env);
  const shutdown = () => void app.stop().then(() => process.exit(0));
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
} catch (error) {
  console.error(error instanceof ConfigError ? `Configuration problem: ${error.message}` : error);
  process.exit(1);
}
