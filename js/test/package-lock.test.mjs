import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const packageUrl = new URL("../package.json", import.meta.url);
const lockUrl = new URL("../package-lock.json", import.meta.url);

test("package lock declares the complete direct dependency set", async () => {
  const packageJson = JSON.parse(await readFile(packageUrl, "utf8"));
  const packageLock = JSON.parse(await readFile(lockUrl, "utf8"));

  assert.deepEqual(
    packageLock.packages[""].dependencies,
    packageJson.dependencies,
  );
});
