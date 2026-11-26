import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

export class PythonBridge {
  #nextId = 1;
  #pending = new Map();
  #failure = null;
  #closing = false;
  constructor(command, args, options = {}) {
    this.child = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      ...options,
    });
    this.child.once("error", (error) =>
      this.#fail(new Error(`Cannot start Python service: ${error.message}`)),
    );
    this.child.once("exit", (code, signal) =>
      this.#fail(new Error(`Python service exited (${signal ?? code})`)),
    );
    this.child.stdin.on("error", (error) => this.#fail(error));
    // Python keeps stdout exclusively for JSON. Do not expose account data in logs.
    this.child.stderr.on("data", (data) => process.stderr.write(data));
    const lines = createInterface({ input: this.child.stdout });
    lines.on("line", (line) => {
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        this.#fail(new Error("Invalid service response"));
        return;
      }
      const pending = this.#pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.#pending.delete(message.id);
      if (message.error)
        pending.reject(
          Object.assign(new Error(message.error.message), message.error),
        );
      else pending.resolve(message.result);
    });
  }
  #fail(error) {
    this.#failure = error;
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.#pending.clear();
  }
  request(method, params = {}, timeout = 45000) {
    if (this.#failure || this.#closing)
      return Promise.reject(this.#failure ?? new Error("Service is closing"));
    if (this.#pending.size >= 128)
      return Promise.reject(new Error("Too many pending requests"));
    const id = this.#nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error("Service request timed out"));
      }, timeout);
      this.#pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(
        JSON.stringify({ id, method, params }) + "\n",
        (error) => {
          if (error) {
            clearTimeout(timer);
            this.#pending.delete(id);
            reject(error);
          }
        },
      );
    });
  }
  close() {
    if (this.#closing) return;
    this.#closing = true;
    this.#fail(new Error("Service closed"));
    this.child.stdin.end();
    const timer = setTimeout(() => this.child.kill(), 1500);
    timer.unref();
    this.child.once("exit", () => clearTimeout(timer));
  }
}
