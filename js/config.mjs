export function normalizeAlgoNetwork(value) {
  const network = (value || "testnet").toLowerCase();
  if (!["mainnet", "testnet"].includes(network)) {
    throw new Error(`Unsupported ALGO_NETWORK: ${value}`);
  }
  return network;
}

export const COMETA_ENV = normalizeAlgoNetwork(process.env.ALGO_NETWORK);
export const NETWORK = COMETA_ENV === "testnet" ? "TestNet" : "MainNet";

export const MONGO_HOST = process.env.MONGODB_HOST;
export const MONGO_PORT = process.env.MONGODB_PORT;

export const META_ASA_IDS = {
  MainNet: 712012773,
  TestNet: 85951079,
};

export const META_TOKEN = META_ASA_IDS[NETWORK];
const ALGONODE_TOKEN = {"x-algo-api-token": process.env.ALGOD_TOKEN};

export const REACH_ALGO_ENV = {
  ALGO_SERVER: process.env.ALGOD_ADDRESS,
  ALGO_PORT: 443,
  ALGO_TOKEN: ALGONODE_TOKEN,
  ALGO_INDEXER_SERVER: process.env.ALGO_INDEXER_ADDRESS,
  ALGO_INDEXER_PORT: 443,
  ALGO_INDEXER_TOKEN: ALGONODE_TOKEN,
  REACH_ISOLATED_NETWORK: 'no',
  ALGO_NODE_WRITE_ONLY: 'no', // XXX no?
};
