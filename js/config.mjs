export const COMETA_ENV = process.env.COMETA_ENVIRONMENT || "test";
export const NETWORK = COMETA_ENV === "test" ? "TestNet" : "MainNet";

export const META_ASA_IDS = {
  MainNet: 712012773,
  TestNet: 85951079,
};

export const META_TOKEN = META_ASA_IDS[NETWORK];
export const MNEMONIC = process.env.DEPLOY_MNEMONIC;

