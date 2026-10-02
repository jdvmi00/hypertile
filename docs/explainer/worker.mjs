const VIDEO = "hypertile-explainer-f42cf8b86a60.mp4";

// A single byte range is sufficient for HTML video playback and seeking.
export function parseRange(header, size) {
  if (!header || !header.startsWith("bytes=")) return null;
  const match = /^bytes=(\d*)-(\d*)$/.exec(header);
  if (!match || (!match[1] && !match[2])) return false;
  let start;
  let end;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) return false;
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)
      || start >= size || end < start) return false;
    end = Math.min(end, size - 1);
  }
  return { offset: start, length: end - start + 1 };
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (!path.startsWith("/media/")) return env.ASSETS.fetch(request);
    const headers = new Headers({
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Range, If-Range, If-None-Match",
      "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges, ETag",
      "X-Content-Type-Options": "nosniff",
      "Accept-Ranges": "bytes",
    });
    if (path !== `/media/${VIDEO}`) return new Response("Not found", { status: 404, headers });
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    if (!["GET", "HEAD"].includes(request.method)) {
      headers.set("Allow", "GET, HEAD, OPTIONS");
      return new Response("Method not allowed", { status: 405, headers });
    }
    const object = await env.MEDIA.head(VIDEO);
    if (!object) return new Response("Not found", { status: 404, headers });
    headers.set("Content-Type", "video/mp4");
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
    headers.set("ETag", object.httpEtag);
    headers.set("Last-Modified", object.uploaded.toUTCString());
    const validator = request.headers.get("If-None-Match");
    if (validator && (validator === "*" || validator.split(",").some(
      value => value.trim().replace(/^W\//, "") === object.httpEtag,
    ))) return new Response(null, { status: 304, headers });

    // HEAD describes the complete representation, regardless of Range.
    const ifRange = request.headers.get("If-Range");
    const mayUseRange = !ifRange || ifRange === object.httpEtag
      || ifRange === object.uploaded.toUTCString();
    const range = request.method === "GET" && mayUseRange
      ? parseRange(request.headers.get("Range"), object.size) : null;
    if (range === false) {
      headers.set("Content-Range", `bytes */${object.size}`);
      return new Response(null, { status: 416, headers });
    }
    headers.set("Content-Length", String(range ? range.length : object.size));
    if (range) headers.set("Content-Range",
      `bytes ${range.offset}-${range.offset + range.length - 1}/${object.size}`);
    if (request.method === "HEAD") return new Response(null, { headers });
    const video = await env.MEDIA.get(VIDEO, range ? { range } : undefined);
    if (!video) return new Response("Not found", { status: 404 });
    return new Response(video.body, { status: range ? 206 : 200, headers });
  },
};
