import { MongoClient } from "mongodb";
import humble from "@reach-sh/humble-sdk";

import {
  MONGO_HOST,
  MONGO_PORT,
  COMETA_ENV,
  NETWORK,
  MNEMONIC,
} from "./config.mjs";

const client = new MongoClient(`mongodb://${MONGO_HOST}:${MONGO_PORT}`);

async function runHumble(collection) {
  const humbleSettings = {
    network: NETWORK,
  };

  if (NETWORK === "TestNet") {
    console.log("YES NETWORK IS TESTNET!");
    humbleSettings.customTriumvirateAddress =
      "XSWSQVQPFMTEQO7UTXGQA5CSSYCDBT2WEN5XWNQ76EBLT2CFRV2HBYKZBE";
    humbleSettings.customTriumvirateId = "93443561";
  }
  console.log(process.env);
  console.log(humbleSettings);

  humble.initHumbleSDK(humbleSettings);
  const reach = humble.createReachAPI();
  const account = await reach.newAccountFromMnemonic(MNEMONIC);

  return humble.subscribeToPoolStream(account, {
    onPoolFetched: async ({ succeeded, data: { pool } }) => {
      if (succeeded && pool) {
        if (pool.tokenAId === "0") {
          pool.tokenAId = 0;
        }

        console.log("found Humble pool: ", pool);

        const query = { poolAddress: pool.poolAddress };
        const update = { $set: pool };
        const options = { upsert: true };
        return collection.updateOne(query, update, options);
      }
    },
  });
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
  console.error(e);
} finally {
  await client.close();
}
