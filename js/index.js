"use strict";

const path = require("path");
const COMETA_ENV = process.env.COMETA_ENVIRONMENT || "testnet";

require("dotenv").config({
  path: path.resolve(__dirname, `../.env.${COMETA_ENV}`),
});

const net = require("net");

// This is done like this to ensure that Reach is loaded on the start of the server,
// but __after__ the dotenv require (so that all the env vars are loaded into the stdlib correctly).
const COMMANDS_PROMISE = import("./commands.mjs");
const COMETA_SOCK = process.argv[2] || "/tmp/cometa-js-interop.sock";

const server = net.createServer({ allowHalfOpen: true });

server.listen(COMETA_SOCK, async () => {
  await COMMANDS_PROMISE; // pre-load before any calls
  console.log(`JS INTEROP: server listens on ${COMETA_SOCK}`);
});

server.on("connection", async (c) => {
  let response = {};
  try {
    const { command, body } = await readJsonFromSocket(c);
    response = await main(command, body);
  } catch (err) {
    response = { error: err.message, stack: err.stack };
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

function readJsonFromSocket(sock) {
  let inputChunks = [];

  sock.resume();
  sock.setEncoding("utf8");

  sock.on("data", function (chunk) {
    inputChunks.push(chunk);
  });

  return new Promise((resolve, reject) => {
    sock.on("end", function () {
      let inputJSON = inputChunks.join();
      resolve(JSON.parse(inputJSON));
    });
    sock.on("error", function () {
      reject(Error("error during read"));
    });
    sock.on("timeout", function () {
      reject(Error("timout during read"));
    });
  });
}

const main = async (cmd, params) => {
  const COMMANDS = await COMMANDS_PROMISE; // should be already resolved here
  if (!(cmd in COMMANDS)) {
    throw new Error(
      `undefined command ${cmd}; expected one of ${JSON.stringify(
        Object.keys(COMMANDS)
      )}`
    );
  }

  const response = await COMMANDS[cmd](params);
  return { response };
};
