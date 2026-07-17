import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import socketSecurity from "../socket-security.js";

const {
  MAX_REQUEST_BYTES,
  assertAllowedCommand,
  readJsonFromSocket,
  secureUnixSocket,
} = socketSecurity;

class FakeSocket extends EventEmitter {
  destroyed = false;

  resume() {}

  setEncoding() {}

  setTimeout() {}

  destroy() {
    this.destroyed = true;
  }
}

test("secureUnixSocket limits access to the current user", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "cometa-socket-"));
  const socketPath = path.join(directory, "interop.sock");
  fs.writeFileSync(socketPath, "");

  try {
    secureUnixSocket(socketPath);
    const mode = fs.statSync(socketPath).mode & 0o777;
    assert.equal(mode, 0o600);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("readJsonFromSocket parses a bounded request", async () => {
  const socket = new FakeSocket();
  const resultPromise = readJsonFromSocket(socket);

  socket.emit("data", '{"command":"health","body":{}}');
  socket.emit("end");

  assert.deepEqual(await resultPromise, { command: "health", body: {} });
  assert.equal(socket.destroyed, false);
});

test("readJsonFromSocket rejects oversized input", async () => {
  const socket = new FakeSocket();
  const resultPromise = readJsonFromSocket(socket);

  socket.emit("data", "x".repeat(MAX_REQUEST_BYTES + 1));

  await assert.rejects(resultPromise, /request exceeded/);
  assert.equal(socket.destroyed, true);
});

test("sidecar command allowlist excludes signing operations", () => {
  assert.doesNotThrow(() => assertAllowedCommand("fetchContractsGlobalViews"));
  assert.doesNotThrow(() => assertAllowedCommand("fetchContractsLocalViews"));
  assert.throws(() => assertAllowedCommand("deployContract"), /unsupported/);
});

test("sidecar implementation stays detached from signing credentials", () => {
  const commandsSource = fs.readFileSync(
    new URL("../commands.mjs", import.meta.url),
    "utf8",
  );
  const indexSource = fs.readFileSync(
    new URL("../index.js", import.meta.url),
    "utf8",
  );
  const backgroundSource = fs.readFileSync(
    new URL("../background.mjs", import.meta.url),
    "utf8",
  );
  const exportedCommands = [
    ...commandsSource.matchAll(/export const (\w+)/g),
  ].map((match) => match[1]);

  assert.doesNotMatch(commandsSource, /newAccountFromMnemonic|deployContract/);
  assert.doesNotMatch(backgroundSource, /newAccountFromMnemonic|MNEMONIC/);
  assert.deepEqual(exportedCommands.sort(), [
    "fetchContractsGlobalViews",
    "fetchContractsLocalViews",
  ]);
  assert.match(indexSource, /delete process\.env\.ALGO_MNEMONIC/);
});
