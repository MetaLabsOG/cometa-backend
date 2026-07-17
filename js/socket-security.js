"use strict";

const fs = require("fs");

const MAX_REQUEST_BYTES = 1024 * 1024;
const SOCKET_READ_TIMEOUT_MS = 30_000;
const ALLOWED_COMMANDS = new Set([
  "fetchContractsGlobalViews",
  "fetchContractsLocalViews",
]);

function assertAllowedCommand(command) {
  if (!ALLOWED_COMMANDS.has(command)) {
    throw new Error("unsupported sidecar command");
  }
}

function secureUnixSocket(socketPath) {
  fs.chmodSync(socketPath, 0o600);
}

function readJsonFromSocket(sock, maxBytes = MAX_REQUEST_BYTES) {
  const inputChunks = [];
  let inputBytes = 0;
  let settled = false;

  sock.resume();
  sock.setEncoding("utf8");
  sock.setTimeout(SOCKET_READ_TIMEOUT_MS);

  return new Promise((resolve, reject) => {
    const fail = (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };

    sock.on("data", (chunk) => {
      if (settled) return;
      inputBytes += Buffer.byteLength(chunk, "utf8");
      if (inputBytes > maxBytes) {
        sock.destroy();
        fail(new Error(`request exceeded ${maxBytes} bytes`));
        return;
      }
      inputChunks.push(chunk);
    });

    sock.on("end", () => {
      if (settled) return;
      try {
        const result = JSON.parse(inputChunks.join(""));
        settled = true;
        resolve(result);
      } catch {
        fail(new Error("invalid JSON request"));
      }
    });

    sock.on("error", () => fail(new Error("socket read failed")));
    sock.on("timeout", () => {
      sock.destroy();
      fail(new Error("socket read timed out"));
    });
  });
}

module.exports = {
  MAX_REQUEST_BYTES,
  assertAllowedCommand,
  readJsonFromSocket,
  secureUnixSocket,
};
