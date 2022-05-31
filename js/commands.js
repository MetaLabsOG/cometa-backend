const crowdsale = import("@metalabsog/crowdsale");
const farm = import("@metalabsog/farm");
const { COMETA_ENV, NETWORK, META_TOKEN } = require("./config");
const { dependencies } = require("./package.json");

const CONTRACT_PKGS = {
  crowdsale,
  farm,
};

const MNEMONIC = process.env.DEPLOY_MNEMONIC;

const crowdsaleWhitelist = async ({ contractId, addr }) => {
  const { backend, reach } = await crowdsale;
  reach.setProviderByName(NETWORK);
  const account = await reach.newAccountFromMnemonic(MNEMONIC);

  const ctc = account.contract(backend, contractId);
  await ctc.a.whitelist(addr);
  return true;
};

const contractVersion = async ({ contractType }) => {
  const key = `@metalabsog/${contractType}`;
  if (!key in dependencies) {
    throw new Error(`unknown contract type ${contractType}`);
  }
  return dependencies[key];
}

const deployContract = async ({ contractType, contractSettings }) => {
  if (!contractType in CONTRACT_PKGS) {
    throw new Error(`unknown contract type ${contractType}`);
  }

  const { deploy, reach } = await CONTRACT_PKGS[contractType];
  reach.setProviderByName(NETWORK);
  const creatorAcc = await reach.newAccountFromMnemonic(MNEMONIC);
  const { contractId } = await deploy(creatorAcc, contractSettings);
  return contractId;
}

// Add functions to these exports and call them from Python by their name and arguments using `calljs`!
module.exports = {
  crowdsaleWhitelist,
  contractVersion,
  deployContract,
};
