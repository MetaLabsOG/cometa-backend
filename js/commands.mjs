import path from "path";
import { fileURLToPath } from "url";
import { readFileSync } from "fs";
import { loadStdlib } from "@reach-sh/stdlib";
import { deployStandardContract } from "@metalabsog/common";
import * as crowdsale from "@metalabsog/crowdsale";
import * as farm from "@metalabsog/farm";
import * as distribution from "@metalabsog/distribution";
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
  distribution,
};

const mapConcurrent = async (ls, fn) => {
  return await Promise.all(ls.map(fn));
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

  const { backend } = CONTRACT_PKGS[contractType];
  const ctc = account.contract(backend);
  const contractId = await deployStandardContract(ctc, contractSettings);
  return contractId;
};

export const fetchContractsGlobalViews = async ({ contractType, ids }) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const { backend } = CONTRACT_PKGS[contractType];
  const results = await mapConcurrent(ids, async (id) => {
    const ctc = account.contract(backend, id);
    try {
      const initial = await ctc.unsafeViews.initial();
      const global = await ctc.unsafeViews.global();
      return { initial, global };
    } catch (e) {
      console.log(e);
      return null;
    }
  });

  const res = {};
  for (let i = 0; i < ids.length; i++) {
    const curRes = results[i];
    if (curRes !== null) {
      res[ids[i]] = results[i];
    }
  }

  return res;
};

export const pingFarms = async ({ type, ids }) => {
  if (type !== "farm" && type !== "distribution") {
    throw new Error(
      `can only ping farms of 'farm' or 'distribution' type, not ${type}`
    );
  }

  const { backend } = CONTRACT_PKGS[contractType];
  return await mapConcurrent(ids, async (id) => {
    const ctc = account.contract(backend, id);
    try {
      await ctc.apis.recalculateRewards();
      return true;
    } catch (e) {
      console.log("recalculateRewards", e);
      return false;
    }
  });
};
