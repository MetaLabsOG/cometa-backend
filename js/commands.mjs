import path from 'path';
import { fileURLToPath } from 'url';
import { readFileSync } from 'fs';
import * as crowdsale from "@metalabsog/crowdsale";
import * as farm from "@metalabsog/farm";
import { COMETA_ENV, NETWORK, META_TOKEN } from "./config.mjs";

// This module is ES module because our contract modules are ES modules, and we want them
// to be loaded synchronously.
// However, ES modules do not have those vars defined by default...
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ...and they also cannot import json without webpack...
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "./package.json")));

const CONTRACT_PKGS = {
  crowdsale,
  farm,
};

// Export functions here and call them from Python by their name and arguments using `calljs`!

export const crowdsaleWhitelist = async ({ contractId, addr }) => {
  const { backend, reach } = crowdsale;
  reach.setProviderByName(NETWORK);
  const account = await reach.newAccountFromMnemonic(MNEMONIC);

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
}

export const deployContract = async ({ contractType, contractSettings }) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const { deploy, reach } = CONTRACT_PKGS[contractType];
  reach.setProviderByName(NETWORK);
  const creatorAcc = await reach.newAccountFromMnemonic(MNEMONIC);
  const { contractId } = await deploy(creatorAcc, contractSettings);
  return contractId;
}