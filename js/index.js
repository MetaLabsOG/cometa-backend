const fs = require('fs/promises');
const path = require("path");
const COMETA_ENV = process.env.COMETA_ENVIRONMENT || "test";

require("dotenv").config({
  path: path.resolve(__dirname, `../.env.${COMETA_ENV}`),
});

const COMMANDS = require("./commands");

function readJsonFromStdin() {
  let stdin = process.stdin;
  let inputChunks = [];

  stdin.resume();
  stdin.setEncoding("utf8");

  stdin.on("data", function (chunk) {
    inputChunks.push(chunk);
  });

  return new Promise((resolve, reject) => {
    stdin.on("end", function () {
      let inputJSON = inputChunks.join();
      resolve(JSON.parse(inputJSON));
    });
    stdin.on("error", function () {
      reject(Error("error during read"));
    });
    stdin.on("timeout", function () {
      reject(Error("timout during read"));
    });
  });
}

let response = {};
let outFile = null;

fs.open(process.argv[2], 'w')
  .then((filehandle) => {
    outFile = filehandle;
    return readJsonFromStdin()
  })
  .then((body) => {
    return main(process.argv.slice(3), body);
  })
  .then((result) => {
    response = result;
  })
  .catch((err) => {
    response = { error: err.message, stack: err.stack };
  })
  .finally(() => {
    const strResponse = JSON.stringify(response);
    outFile.write(`${strResponse}\n`);
  });

const main = async (argv, params) => {
  if (argv.length !== 1) {
    throw new Error(
      `script expects exactly one argument (command name), ${argv.length} given`
    );
  }

  const cmd = argv[0];
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
