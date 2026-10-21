/**
 * Private, one-purpose intake for The Weed Doctor. No public bucket URLs.
 * Source data is fetched directly from Discord CDN into an R2 binding;
 * the Discord bot never buffers waiting photos in Python memory.
 * Required secrets: GROWER_INTAKE_TOKEN; binding: INTAKE.
 */
const LIMIT = 8 * 1024 * 1024;
const KEY = /^photos\/[0-9]{1,20}\/[0-9]{1,20}\/[0-9a-f]{32}$/;
const SOURCE_HOSTS = new Set(["cdn.discordapp.com", "media.discordapp.net"]);

function deny(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
  });
}
export default {
  async fetch(request, env) {
    if (!env.INTAKE || !env.GROWER_INTAKE_TOKEN || env.GROWER_INTAKE_TOKEN.length < 32) {
      return deny(503, "Not configured");
    }
    if (request.headers.get("Authorization") !== "Bearer " + env.GROWER_INTAKE_TOKEN) {
      return deny(401, "Unauthorized");
    }
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/v1/objects/")) return deny(404, "Not found");
    const key = decodeURIComponent(url.pathname.slice("/v1/objects/".length));
    if (!KEY.test(key)) return deny(400, "Invalid key");
    if (request.method === "POST") {
      let form;
      try { form = await request.json(); } catch { return deny(400, "Invalid request"); }
      const size = Number(form?.size);
      if (!Number.isSafeInteger(size) || size < 1 || size > LIMIT ||
          typeof form?.url !== "string" || form.url.length > 2100) {
        return deny(400, "Invalid image metadata");
      }
      let source;
      try { source = new URL(form.url); } catch { return deny(400, "Invalid image URL"); }
      if (source.protocol !== "https:" || !SOURCE_HOSTS.has(source.hostname) ||
          !/^\/(?:ephemeral-)?attachments\//.test(source.pathname) ||
          source.username || source.password || source.port) {
        return deny(400, "Only Discord attachment URLs may be staged");
      }
      // Never follow redirects to arbitrary origins. Discord's own CDN
      // controls Content-Type/Length; verify both before passing its body to R2.
      const fetched = await fetch(source.toString(), { redirect: "manual", headers: { "Accept": "image/*" } });
      if (fetched.status !== 200 || !fetched.body) return deny(502, "Source unavailable");
      const length = Number(fetched.headers.get("Content-Length"));
      const contentType = fetched.headers.get("Content-Type")?.split(";")[0]?.toLowerCase();
      if (length !== size || !["image/jpeg", "image/png", "image/webp"].includes(contentType)) {
        await fetched.body.cancel();
        return deny(415, "Source size or format mismatch");
      }
      try {
        await env.INTAKE.put(key, fetched.body, {
          httpMetadata: { contentType: "application/octet-stream" },
          customMetadata: { expires: String(Date.now() + 30 * 60 * 1000) }
        });
        return deny(201, "Stored");
      } catch {
        return deny(503, "Private staging unavailable");
      }
    }
    if (request.method === "HEAD") {
      return new Response(null, {
        status: (await env.INTAKE.head(key)) ? 200 : 404,
        headers: { "Cache-Control": "no-store" }
      });
    }
    if (request.method === "GET") {
      const obj = await env.INTAKE.get(key);
      if (!obj) return deny(404, "Not found");
      return new Response(obj.body, {
        status: 200,
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Length": String(obj.size),
          "Cache-Control": "private, no-store"
        }
      });
    }
    if (request.method === "DELETE") {
      await env.INTAKE.delete(key);
      return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
    }
    return deny(405, "Method not allowed");
  }
};
