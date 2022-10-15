import path from "path";
import semver from "semver";
import { fileURLToPath } from "url";
import { readFileSync } from "fs";
import { loadStdlib } from "@reach-sh/stdlib";
import algosdk from 'algosdk';
import * as RHC from '@reach-sh/stdlib/dist/cjs/ALGO_ReachHTTPClient.js';
import * as UTBC from '@reach-sh/stdlib/dist/cjs/ALGO_UTBC.js';

import { deployStandardContract } from "@metalabsog/common";

import * as crowdsale from "@metalabsog/crowdsale";
import * as farm_17_2_4 from "metalabsog-farm-17_2_4";
import * as farm_17_2_5 from "metalabsog-farm-17_2_5";
import * as distribution_17_0_4 from "metalabsog-distribution-17_0_4";
import * as distribution_17_0_5 from "metalabsog-distribution-17_0_5";

import { NETWORK, MNEMONIC, REACH_ALGO_ENV } from "./config.mjs";

// This module is ES module because our contract modules are ES modules, and we want them
// to be loaded synchronously.
// However, ES modules do not have those vars defined by default...
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ...and they also cannot import json without webpack...
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "./package.json")));

// FUCK THAT
//
const localhostProviderEnv = {
    ALGO_SERVER: 'http://localhost',
    ALGO_PORT: '4180',
    ALGO_TOKEN: 'c87f5580d7a866317b4bfe9e8b8d1dda955636ccebfa88c12b414db208dd9705',
    ALGO_INDEXER_SERVER: 'http://localhost',
    ALGO_INDEXER_PORT: '8980',
    ALGO_INDEXER_TOKEN: 'reach-devnet',
    REACH_ISOLATED_NETWORK: 'yes',
    ALGO_NODE_WRITE_ONLY: 'no',
};

function truthyEnv(v) {
    if (!v) return false;
    return !['0', 'false', 'f', '#f', 'no', 'off', 'n', ''].includes(v && v.toLowerCase && v.toLowerCase());
}

function envDefaultsALGO(env) {
    return { ...localhostProviderEnv, ...env };
}

// These two functions allow us to use PureStake API with Reach without issue
export function indexerFromEnv(env) {
    const { ALGO_INDEXER_SERVER, ALGO_INDEXER_PORT, ALGO_INDEXER_TOKEN } = env;
    const port = ALGO_INDEXER_PORT || undefined; // UTBC checks for undefined
    const token =
        typeof ALGO_INDEXER_TOKEN === 'string' ? { 'X-Indexer-API-Token': ALGO_INDEXER_TOKEN } : ALGO_INDEXER_TOKEN;

    const utbc = new UTBC.URLTokenBaseHTTPClient(token, ALGO_INDEXER_SERVER, port);
    const rhc = new RHC.ReachHTTPClient(utbc, 'indexer', async (e) => {
        // Do nothing
    });
    return [rhc, new algosdk.Indexer(rhc)];
}

export function algodClientFromEnv(env) {
    const { ALGO_SERVER, ALGO_PORT, ALGO_TOKEN } = env;
    const port = ALGO_PORT || undefined; // UTBC checks for undefiend
    const token = typeof ALGO_TOKEN === 'string' ? { 'X-Algo-API-Token': ALGO_TOKEN } : ALGO_TOKEN;

    const utbc = new UTBC.URLTokenBaseHTTPClient(token, ALGO_SERVER, port);
    const rhc = new RHC.ReachHTTPClient(utbc, 'algodv2', async (e) => {
        // Do nothing
    });
    return [rhc, new algosdk.Algodv2(rhc)];
}

/**
 * This redefinition allows us to redefine `getProvider` properly, and it also allows us to make
 * a provider synchronously (e.g. to make a default provider and reuse algod client and indexer in `AppContext`)
 */
export function makeProviderByEnv(env) {
    const fullEnv = envDefaultsALGO(env);
    const [algod_bc, algodClient] = algodClientFromEnv(fullEnv);
    const [indexer_bc, indexer] = indexerFromEnv(fullEnv);
    const isIsolatedNetwork = truthyEnv(fullEnv.REACH_ISOLATED_NETWORK);
    const nodeWriteOnly = truthyEnv(fullEnv.ALGO_NODE_WRITE_ONLY);
    const errmsg = (s) =>
        `Providers created by environment ${s}. Calling setProviderByEnv or setProviderByName removes this capability. Try removing calls to those functions.`;

    const getDefaultAddress = async () => {
        throw new Error(errmsg(`do not have default addresses`));
    };

    const signAndPostTxns = async (txns, options) => {
        void options;
        const stxns = txns.map((txn) => {
            if (txn.stxn) {
                return txn.stxn;
            }
            throw new Error(errmsg(`cannot interactively sign`));
        });
        const bs = stxns.map((stxn) => Buffer.from(stxn, 'base64'));
        await algodClient.sendRawTransaction(bs).do();
    };

    return {
        algod_bc,
        indexer_bc,
        algodClient,
        indexer,
        nodeWriteOnly,
        isIsolatedNetwork,
        getDefaultAddress,
        signAndPostTxns,
    };
}


// Setting up (and remembering!) the reach stuff
const reach = loadStdlib(process.env);
const account = await reach.newAccountFromMnemonic(MNEMONIC);
reach.setProvider(makeProviderByEnv(REACH_ALGO_ENV));

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

export const fetchContractsLocalViews = async ({
  contractType,
  idVersions,
  walletAddress
}) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const results = await mapConcurrent(idVersions, async ({ id, version }) => {
    try {
      const { backend } = CONTRACT_PKGS[contractType][version];
      const ctc = account.contract(backend, id);
      const local = await ctc.unsafeViews.local(walletAddress);
      return local;
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
