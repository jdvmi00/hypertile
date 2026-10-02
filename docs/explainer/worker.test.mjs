import assert from "node:assert/strict";
import test from "node:test";
import worker, { parseRange } from "./worker.mjs";

const url = "https://hypertile.jimmartin.workers.dev/media/hypertile-explainer-f42cf8b86a60.mp4";
const bytes = new TextEncoder().encode("0123456789");
const etag = '"video-v1"';
const gets = [];
const env = {
  ASSETS: { fetch: () => new Response("player") },
  MEDIA: {
    head: async () => ({ size: bytes.length, httpEtag: etag, uploaded: new Date("2026-10-02T00:00:00Z") }),
    get: async (key, options) => {
      gets.push({ key, options });
      const range = options?.range;
      return { body: range ? bytes.slice(range.offset, range.offset + range.length) : bytes };
    },
  },
};
const fetchVideo = (options) => worker.fetch(new Request(url, options), env);

test("byte ranges support seeking, suffixes, bounds, and invalid input", () => {
  assert.deepEqual(parseRange("bytes=2-5", 10), { offset: 2, length: 4 });
  assert.deepEqual(parseRange("bytes=7-", 10), { offset: 7, length: 3 });
  assert.deepEqual(parseRange("bytes=-3", 10), { offset: 7, length: 3 });
  assert.deepEqual(parseRange("bytes=7-999", 10), { offset: 7, length: 3 });
  assert.deepEqual(parseRange("bytes=-999", 10), { offset: 0, length: 10 });
  for (const invalid of ["bytes=10-", "bytes=5-3", "bytes=-0", "bytes=-", "bytes=0-1,5-6", "bytes=9007199254740992-"]) {
    assert.equal(parseRange(invalid, 10), false);
  }
  assert.equal(parseRange(null, 10), null);
  assert.equal(parseRange("unknown=2-5", 10), null);
});

test("full and partial responses contain the correct bytes and media headers", async () => {
  const full = await fetchVideo();
  assert.equal(full.status, 200);
  assert.equal(full.headers.get("Content-Type"), "video/mp4");
  assert.equal(full.headers.get("Content-Length"), "10");
  assert.equal(full.headers.get("Access-Control-Allow-Origin"), "*");
  assert.equal(await full.text(), "0123456789");
  const partial = await fetchVideo({ headers: { Range: "bytes=2-5" } });
  assert.equal(partial.status, 206);
  assert.equal(partial.headers.get("Content-Range"), "bytes 2-5/10");
  assert.equal(partial.headers.get("Content-Length"), "4");
  assert.equal(await partial.text(), "2345");
  const invalid = await fetchVideo({ headers: { Range: "bytes=10-" } });
  assert.equal(invalid.status, 416);
  assert.equal(invalid.headers.get("Content-Range"), "bytes */10");
});

test("HEAD and conditional requests avoid fetching the video body", async () => {
  const count = gets.length;
  const head = await fetchVideo({ method: "HEAD", headers: { Range: "bytes=2-5" } });
  assert.equal(head.status, 200);
  assert.equal(head.headers.get("Content-Length"), "10");
  assert.equal(await head.text(), "");
  const cached = await fetchVideo({ headers: { "If-None-Match": `W/${etag}` } });
  assert.equal(cached.status, 304);
  assert.equal(gets.length, count);
  const changed = await fetchVideo({ headers: { Range: "bytes=2-5", "If-Range": '"older-video"' } });
  assert.equal(changed.status, 200);
  assert.equal(await changed.text(), "0123456789");
});

test("routing exposes only the intended video and read methods", async () => {
  assert.equal((await worker.fetch(new Request("https://example.com/"), env)).status, 200);
  assert.equal((await worker.fetch(new Request("https://example.com/media/private.mp4"), env)).status, 404);
  assert.equal((await fetchVideo({ method: "OPTIONS" })).status, 204);
  assert.equal((await fetchVideo({ method: "POST" })).status, 405);
  const missing = { ...env, MEDIA: { head: async () => null } };
  assert.equal((await worker.fetch(new Request(url), missing)).status, 404);
});
