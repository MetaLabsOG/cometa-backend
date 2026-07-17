"use strict";

const path = require("path");
const {
  assertAllowedCommand,
  readJsonFromSocket,
  secureUnixSocket,
} = require("./socket-security.js");

require("dotenv").config({
  path: path.resolve(__dirname, `../.env`),
});
delete process.env.ALGO_MNEMONIC;
delete process.env.REKEYED_MNEMONIC;

// Enable HTTP_PROXY/HTTPS_PROXY support for all Node.js HTTP requests
if (process.env.HTTPS_PROXY || process.env.HTTP_PROXY) {
  process.env.GLOBAL_AGENT_HTTP_PROXY = process.env.HTTP_PROXY || '';
  process.env.GLOBAL_AGENT_HTTPS_PROXY = process.env.HTTPS_PROXY || '';
  process.env.GLOBAL_AGENT_NO_PROXY = process.env.NO_PROXY || '';
  require("global-agent").bootstrap();
}

// This is background worker on the JS side. Currently it is only used for updating
// the MongoDB cache with Humble pools information.
const BACKGROUND_PROMISE = process.env.SYNC_HUMBLE_POOLS === "1" ? import("./background.mjs") : null;

const net = require("net");

// This is done like this to ensure that Reach is loaded on the start of the server,
// but __after__ the dotenv require (so that all the env vars are loaded into the stdlib correctly).
const COMMANDS_PROMISE = import("./commands.mjs");
const COMETA_SOCK = process.argv[2] || "/tmp/cometa-js-interop.sock";

// Contract state may include user-specific financial data, so the IPC endpoint
// must never be accessible to other users on a shared host.
process.umask(0o077);
const server = net.createServer({ allowHalfOpen: true });

server.listen(COMETA_SOCK, async () => {
  secureUnixSocket(COMETA_SOCK);
  await COMMANDS_PROMISE; // pre-load before any calls
  console.log(`JS INTEROP: server listens on ${COMETA_SOCK}`);
});

server.on("connection", async (c) => {
  let response = {};
  try {
    const { command, body } = await readJsonFromSocket(c);
    assertAllowedCommand(command);
    response = await main(command, body);
  } catch (err) {
    console.error("JS interop command failed", err);
    response = { error: err instanceof Error ? err.message : "command failed" };
  }

  const strResponse = JSON.stringify(response);
  c.write(`${strResponse}\n`);
});

server.on("close", () => {
  console.log("JS INTEROP: shutting down");
});

server.on("error", (err) => {
  server.close();
  throw err;
});

process.on("exit", () => {
  server.close();
});

const endHandler = (signal) => {
  console.log(`Received signal: ${signal}`);
  process.exit(0);
};

process.on("SIGINT", endHandler);
process.on("SIGTERM", endHandler);
process.on("disconnect", () => endHandler("disconnect"));

const main = async (cmd, params) => {
  const COMMANDS = await COMMANDS_PROMISE; // should be already resolved here
  if (!Object.prototype.hasOwnProperty.call(COMMANDS, cmd)) {
    throw new Error(
      `undefined command ${cmd}; expected one of ${JSON.stringify(
        Object.keys(COMMANDS)
      )}`
    );
  }

  const response = await COMMANDS[cmd](params);
  return { response };
};
