import assert from "node:assert/strict";
import test from "node:test";

import {normalizeAlgoNetwork} from "../config.mjs";
import {getContractVersions} from "../contract-registry.mjs";

test("normalizeAlgoNetwork defaults and normalizes supported networks", () => {
  assert.equal(normalizeAlgoNetwork(undefined), "testnet");
  assert.equal(normalizeAlgoNetwork("MAINNET"), "mainnet");
});

test("normalizeAlgoNetwork rejects unknown networks", () => {
  assert.throws(
    () => normalizeAlgoNetwork("betanet"),
    /Unsupported ALGO_NETWORK: betanet/,
  );
});

test("getContractVersions accepts only own registry keys", () => {
  const registry = {farm: {"1.0.0": {}}};

  assert.deepEqual(getContractVersions(registry, "farm"), registry.farm);
  assert.throws(
    () => getContractVersions(registry, "distribution"),
    /unknown contract type distribution/,
  );
  assert.throws(
    () => getContractVersions(registry, "toString"),
    /unknown contract type toString/,
  );
});
