import path from "path";
import { fileURLToPath } from "url";
import { readFileSync } from "fs";
import { loadStdlib } from "@reach-sh/stdlib";
import * as crowdsale from "@metalabsog/crowdsale";
import * as farm from "@metalabsog/farm";
import { NETWORK, MNEMONIC } from "./config.mjs";

// This module is ES module because our contract modules are ES modules, and we want them
// to be loaded synchronously.
// However, ES modules do not have those vars defined by default...
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ...and they also cannot import json without webpack...
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "./package.json")));

// Setting up (and remembering!) the reach stuff
const reach = loadStdlib(process.env);
const account = await reach.newAccountFromMnemonic(MNEMONIC);
reach.setProviderByName(NETWORK);

const CONTRACT_PKGS = {
  crowdsale,
  farm,
};

// TODO: this shit is copypasted fucking everywhere, can we do something about it?
const maybeToNullable = (mb) => {
  if (mb[0] === "Some") return mb[1];
  return null;
};

const isBigNumber = (n) =>
  Object.prototype.hasOwnProperty.call(n, "_isBigNumber");

const convertBns = (obj) => {
  if (isBigNumber(obj)) {
    return obj.toNumber();
  } else if (obj instanceof Array) {
    return obj.map((e) => convertBns(e));
  } else if (obj instanceof Object) {
    return Object.keys(obj).reduce((o, k) => {
      o[k] = convertBns(obj[k]);
      return o;
    }, {});
  } else {
    return obj;
  }
};

// Export functions here and call them from Python by their name and arguments using `calljs`!

export const crowdsaleWhitelist = async ({ contractId, addr }) => {
  const { backend } = crowdsale;

  const ctc = account.contract(backend, contractId);
  await ctc.a.whitelist(addr);
  return true;
};

export const contractVersion = async ({ contractType }) => {
  const key = `@metalabsog/${contractType}`;
  if (!key in pkg.dependencies) {
    throw new Error(`unknown contract type ${contractType}`);
  }
  return pkg.dependencies[key];
};

export const deployContract = async ({ contractType, contractSettings }) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const { deploy } = CONTRACT_PKGS[contractType];
  const { contractId } = await deploy(account, contractSettings);
  return contractId;
};

export const fetchContractsGlobalViews = async ({ contractType, ids }) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const { backend } = CONTRACT_PKGS[contractType];
  const promises = ids.map(async (id) => {
    const ctc = account.contract(backend, id);
    const initial = await ctc.views.initial().then(maybeToNullable).then(convertBns);
    const global = await ctc.views.global().then(maybeToNullable).then(convertBns);
    return { initial, global };
  });

  const results = await Promise.all(promises);
  const res = {};
  for (let i = 0; i < ids.length; i++) {
    res[ids[i]] = results[i];
  }

  return res;
};
