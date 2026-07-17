export function getContractVersions(registry, contractType) {
  if (!Object.hasOwn(registry, contractType)) {
    throw new Error(`unknown contract type ${contractType}`);
  }
  return registry[contractType];
}
