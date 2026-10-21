// Runtime privacy and lifecycle tests for the private Cloudflare Worker.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const code = await readFile(new URL("../cloudflare/grower-intake-worker.js", import.meta.url), "utf8");
const { default: handler } = await import(
  "data:text/javascript;base64," + Buffer.from(code).toString("base64")
);
const key = "photos/5/1/" + "a".repeat(32);
const token = "secret" + "x".repeat(50);
const url = "https://worker.example/v1/objects/" + key;
const request = (method, body) => new Request(url, {
  method, headers: { Authorization: "Bearer " + token },
  ...(body ? { body: JSON.stringify(body), headers: {
    Authorization: "Bearer " + token, "Content-Type": "application/json"
  } } : {})
});

function fixture(expires) {
  const objects = new Map();
  const removed = [];
  objects.set(key, { key, size: 1,
    customMetadata: { expires: String(expires) },
    body: new Response("x").body
  });
  const bucket = {
    async head(k) { return objects.get(k) ?? null; },
    async get(k) { return objects.get(k) ?? null; },
    async delete(keys) {
      for (const k of Array.isArray(keys) ? keys : [keys]) {
        removed.push(k);
        objects.delete(k);
      }
    },
    async list() {
      return { objects: [...objects.values()], truncated: false };
    },
    async put(k, body, opts) {
      objects.set(k, { key: k, size: 1,
        customMetadata: opts.customMetadata, body });
    }
  };
  return { env: { INTAKE: bucket, GROWER_INTAKE_TOKEN: token },
    removed, objects };
}

test("worker does not expose stored photos without secret", async () => {
  const { env } = fixture(Date.now()+60000);
  const r = await handler.fetch(new Request(url), env);
  assert.equal(r.status, 401);
});

test("unexpired photo can be read, without exposing public caching", async () => {
  const { env } = fixture(Date.now()+60000);
  const r = await handler.fetch(request("GET"), env);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("Cache-Control"), "private, no-store");
});

test("expired images are rejected and deleted from R2 on GET", async () => {
  const { env, objects, removed } = fixture(Date.now()-60000);
  const r = await handler.fetch(request("GET"), env);
  assert.equal(r.status, 404);
  assert.equal(objects.size, 0);
  assert.deepEqual(removed, [key]);
});

test("expired images are rejected and deleted from R2 on HEAD", async () => {
  const { env, objects } = fixture(Date.now()-60000);
  const r = await handler.fetch(request("HEAD"), env);
  assert.equal(r.status, 404);
  assert.equal(objects.size, 0);
});

test("scheduled sweep deletes expired objects but not live ones", async () => {
  const { env, objects } = fixture(Date.now()-60000);
  const live = key.replaceAll("a", "b");
  objects.set(live, { key:live,size:1,customMetadata:{
    expires:String(Date.now()+60000) } });
  await handler.scheduled({}, env);
  assert.equal(objects.has(key), false);
  assert.equal(objects.has(live), true);
});

test("worker does not fetch arbitrary external domains", async () => {
  const { env } = fixture(Date.now()+60000);
  const r = await handler.fetch(request("POST", {
    size:1, url:"https://evil.example/attachments/1/2/image.png"
  }), env);
  assert.equal(r.status, 400);
});
