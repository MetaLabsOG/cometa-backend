import { MongoClient } from "mongodb";
import humble, { fetchLiquidityPool } from "@reach-sh/humble-sdk";

import {
  MONGO_HOST,
  MONGO_PORT,
  COMETA_ENV,
  NETWORK,
  MNEMONIC,
} from "./config.mjs";

const client = new MongoClient(`mongodb://${MONGO_HOST}:${MONGO_PORT}`);

async function sleep(time) {
  return new Promise((resolve) => setTimeout(resolve, time));
}

async function upsertPool(collection, pool) {
  if (pool.tokenAId === "0") {
    pool.tokenAId = 0;
  }

  const query = { poolAddress: pool.poolAddress };
  const update = { $set: pool };
  const options = { upsert: true };
  return collection.updateOne(query, update, options);
}

async function updateHumblePools(account, collection, waitSecs) {
  console.log(`updating Humble pools`);

  while (true) {
    await sleep(waitSecs * 1000);

    const cursor = collection.find(
      {},
      { projection: { poolAddress: 1, n2nn: 1 } }
    );

    await cursor.forEach(async ({ poolAddress, n2nn }) => {
      const { succeeded, data } = await fetchLiquidityPool(account, {
        poolAddress,
        n2nn,
      });

      if (succeeded) {
        return upsertPool(collection, data.pool);
      }
    });
  }
}

async function runHumble(collection) {
  const humbleSettings = {
    network: NETWORK,
  };

  if (NETWORK === "TestNet") {
    humbleSettings.customTriumvirateAddress =
      "XSWSQVQPFMTEQO7UTXGQA5CSSYCDBT2WEN5XWNQ76EBLT2CFRV2HBYKZBE";
    humbleSettings.customTriumvirateId = "93443561";
  }

  humble.initHumbleSDK(humbleSettings);
  const reach = humble.createReachAPI();
  const account = await reach.newAccountFromMnemonic(MNEMONIC);

  const streamPromise = humble.subscribeToPoolStream(account, {
    onPoolFetched: async ({ succeeded, data: { pool } }) => {
      if (succeeded && pool) {
        console.log(`Humble pool: ${pool.poolAddress} fetched`);
        return upsertPool(collection, pool);
      }
    },
  });

  const updatePromise = updateHumblePools(account, collection, 300);

  return Promise.all([streamPromise, updatePromise]);
}

try {
  console.log("JS: try to connect to Mongo");
  await client.connect();
  const collection = client
    .db(COMETA_ENV.toUpperCase())
    .collection("humblePools");
  console.log("JS connected to Mongo");

  await runHumble(collection);
} catch (e) {
  console.error('BACKGROUND HUMBLE FETCHER ERROR', e);
} finally {
  console.log('Fuck Humble ok?');
  await client.close();
  console.log('Didnt even wanted it so much');
}
