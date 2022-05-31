const COMETA_ENV = process.env.COMETA_ENVIRONMENT || "test";
const NETWORK = COMETA_ENV === "test" ? "TestNet" : "MainNet";

const META_ASA_IDS = {
  MainNet: 712012773,
  TestNet: 85951079,
};

const META_TOKEN = META_ASA_IDS[NETWORK];

module.exports = {
  COMETA_ENV,
  NETWORK,
  META_TOKEN,
};
