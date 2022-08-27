import path from "path";
import semver from "semver";
import { fileURLToPath } from "url";
import { readFileSync } from "fs";
import { loadStdlib } from "@reach-sh/stdlib";
import { deployStandardContract } from "@metalabsog/common";

import * as crowdsale from "@metalabsog/crowdsale";
import * as farm_17_2_4 from "metalabsog-farm-17_2_4";
import * as farm_17_2_5 from "metalabsog-farm-17_2_5";
import * as distribution_17_0_4 from "metalabsog-distribution-17_0_4";
import * as distribution_17_0_5 from "metalabsog-distribution-17_0_5";

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
  crowdsale: {
    "17.0.0": crowdsale,
  },
  farm: {
    "17.2.4": farm_17_2_4,
    "17.2.5": farm_17_2_5,
  },
  distribution: {
    "17.0.4": distribution_17_0_4,
    "17.0.5": distribution_17_0_5,
  },
};

const latestVersion = (versions) =>
  versions.reduce(
    (prev, next) => (semver.gte(next, prev) ? next : prev),
    "0.0.0"
  );

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
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  return latestVersion(Object.keys(CONTRACT_PKGS[contractType]));
};

export const deployContract = async ({
  contractType,
  contractSettings,
  version,
}) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const versions = CONTRACT_PKGS[contractType];
  if (!version) {
    version = latestVersion(Object.keys(versions));
  }

  const { backend } = versions[version];
  const ctc = account.contract(backend);
  const contractId = await deployStandardContract(ctc, contractSettings);
  return contractId;
};

export const fetchContractsGlobalViews = async ({
  contractType,
  idVersions,
}) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const results = await mapConcurrent(idVersions, async ({ id, version }) => {
    try {
      const { backend } = CONTRACT_PKGS[contractType][version];
      const ctc = account.contract(backend, id);
      const initial = await ctc.unsafeViews.initial();
      const global = await ctc.unsafeViews.global();
      return { initial, global };
    } catch (e) {
      console.log(e);
      return null;
    }
  });

  const res = {};
  for (let i = 0; i < idVersions.length; i++) {
    const curRes = results[i];
    if (curRes !== null) {
      res[idVersions[i].id] = results[i];
    }
  }

  return res;
};
