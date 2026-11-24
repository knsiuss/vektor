/**
 * Start the Vektor backend (uvicorn --reload) and the Next.js dev server together.
 *
 * `npm run dev` uses this so one command brings up both sides. Each child is prefixed in the
 * terminal and hot-reloads on its own. Ctrl+C, or one process dying, stops the other.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const frontendDir = path.resolve(import.meta.dirname, "..");
const rootDir = path.resolve(frontendDir, "..");
const BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health";

const children = new Map();
let stopping = false;

function prefixLines(prefix, chunk) {
  return chunk.toString().replace(/^(?=.)/gm, `${prefix} `);
}

function start(name, command, args, cwd) {
  const child = spawn(command, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
  children.set(name, child);
  const prefix = `[${name}]`;
  child.stdout.on("data", (chunk) => process.stdout.write(prefixLines(prefix, chunk)));
  child.stderr.on("data", (chunk) => process.stderr.write(prefixLines(prefix, chunk)));
  child.on("error", (error) => {
    console.error(`${prefix} could not start: ${error.message}`);
  });
  child.on("exit", (code, signal) => {
    children.delete(name);
    if (stopping) return;
    console.error(`${prefix} exited (${signal ?? code ?? "unknown"}). Stopping everything.`);
    void stop(code ?? 1);
  });
  return child;
}

function terminate(child) {
  if (child.exitCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    if (process.platform === "win32" && child.pid) {
      // uvicorn --reload spawns workers; taskkill /T takes the whole tree down.
      const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
      killer.on("exit", () => resolve());
      return;
    }
    child.once("exit", () => resolve());
    child.kill("SIGTERM");
  });
}

async function stop(exitCode = 0) {
  if (!stopping) {
    stopping = true;
    await Promise.all([...children.values()].map(terminate));
  }
  process.exit(exitCode);
}

async function backendIsRunning() {
  try {
    const response = await fetch(BACKEND_HEALTH_URL, { signal: AbortSignal.timeout(1_500) });
    return response.ok;
  } catch {
    return false;
  }
}

function backendCommand() {
  const venvPython = path.join(
    rootDir,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  if (existsSync(venvPython)) return { command: venvPython, args: [] };
  // Fall back to the project-managed interpreter when the venv is not created yet.
  return { command: "uv", args: ["run"] };
}

async function main() {
  const backendArgs = [
    "-m",
    "uvicorn",
    "api.main:app",
    "--app-dir",
    "src",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
    "--reload",
  ];

  if (await backendIsRunning()) {
    console.log("[backend] already running on http://127.0.0.1:8000");
  } else {
    const { command, args } = backendCommand();
    if (command === "uv") {
      console.warn("[backend] no .venv found; falling back to `uv run` (run `uv sync` first).");
    }
    start("backend", command, [...args, ...backendArgs], rootDir);
  }

  const npm =
    process.platform === "win32"
      ? { command: process.env.ComSpec ?? "cmd.exe", args: ["/c", "npm", "run", "dev:next"] }
      : { command: "npm", args: ["run", "dev:next"] };
  start("frontend", npm.command, npm.args, frontendDir);
}

process.on("SIGINT", () => void stop(0));
process.on("SIGTERM", () => void stop(0));

main().catch((error) => {
  console.error(error);
  void stop(1);
});
