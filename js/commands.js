const { backend, reach } = require("@metalabsog/crowdsale");
const { COMETA_ENV, NETWORK, META_TOKEN } = require("./config");

const crowdsaleWhitelist = async ({ contractId, addr }) => {
  reach.setProviderByName(NETWORK);
  const account = await reach.newAccountFromMnemonic(process.env.algo_mnemonic);
  const ctc = account.contract(backend, contractId);
  await ctc.a.whitelist(addr);
  return true;
};

// Add functions to these exports and call them from Python by their name and arguments!
module.exports = {
  crowdsaleWhitelist,
};
