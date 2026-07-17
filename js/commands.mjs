import {loadStdlib} from "@reach-sh/stdlib";
import algosdk from 'algosdk';

import * as RHC from '@reach-sh/stdlib/dist/cjs/ALGO_ReachHTTPClient.js';
import * as UTBC from '@reach-sh/stdlib/dist/cjs/ALGO_UTBC.js';

import * as farm_17_2_4 from "metalabsog-farm-17_2_4";
import * as farm_17_2_5 from "metalabsog-farm-17_2_5";
import * as distribution_17_0_4 from "metalabsog-distribution-17_0_4";
import * as distribution_17_0_5 from "metalabsog-distribution-17_0_5";

import {REACH_ALGO_ENV} from "./config.mjs";
import {getContractVersions} from "./contract-registry.mjs";

const localhostProviderEnv = {
    ALGO_SERVER: 'http://localhost',
    ALGO_PORT: '4180',
    ALGO_TOKEN: process.env.REACH_DEVNET_ALGOD_TOKEN,
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
function indexerFromEnv(env) {
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

function algodClientFromEnv(env) {
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
function makeProviderByEnv(env) {
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


// Global views do not need a funded signer. Keep this production sidecar
// detached from the deployment mnemonic by using a public, keyless account.
const reach = loadStdlib(REACH_ALGO_ENV);
const viewAccountAddress = algosdk.encodeAddress(new Uint8Array(32));
const account = await reach.connectAccount({addr: viewAccountAddress});
reach.setProvider(makeProviderByEnv(REACH_ALGO_ENV));

const CONTRACT_PKGS = {
  farm: {
    "17.2.4": farm_17_2_4,
    "17.2.5": farm_17_2_5,
  },
  distribution: {
    "17.0.4": distribution_17_0_4,
    "17.0.5": distribution_17_0_5,
  },
};

const mapConcurrent = async (ls, fn) => {
  return await Promise.all(ls.map(fn));
};

export const fetchContractsGlobalViews = async ({
  contractType,
  idVersions,
}) => {
  const versions = getContractVersions(CONTRACT_PKGS, contractType);
  
  const results = await mapConcurrent(idVersions, async ({ id, version }) => {
    try {
      const { backend } = versions[version];
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
  const versions = getContractVersions(CONTRACT_PKGS, contractType);

  const results = await mapConcurrent(idVersions, async ({ id, version }) => {
    try {
      const { backend } = versions[version];
      const ctc = account.contract(backend, id);
      return await ctc.unsafeViews.local(walletAddress);
    } catch (e) {
      console.log(e);
      return null;
    }
  });

  const res = {};
  for (let i = 0; i < idVersions.length; i++) {
    const curRes = results[i];
    if (curRes !== null) {
      res[idVersions[i].id] = curRes;
    }
  }

  return res;
};
