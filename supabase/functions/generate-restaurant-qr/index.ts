import QRCode from "npm:qrcode";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const PUBLIC_BASE_URL = Deno.env.get("PUBLIC_BASE_URL") ?? "";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return json({ error: "METHOD_NOT_ALLOWED" }, 405);
  }

  const authorization = request.headers.get("Authorization");
  if (!authorization) {
    return json({ error: "MISSING_AUTH" }, 401);
  }

  const userClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: authorization } },
  });
  const serviceClient = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  const {
    data: { user },
    error: authError,
  } = await userClient.auth.getUser();

  if (authError || !user) {
    return json({ error: "INVALID_AUTH" }, 401);
  }

  const appMetadata = user.app_metadata ?? {};
  if (appMetadata.role !== "OWNER") {
    return json({ error: "FORBIDDEN" }, 403);
  }

  const body = await request.json().catch(() => null);
  const restaurantId = String(body?.restaurant_id ?? "").trim();
  const slug = String(body?.slug ?? "").trim();

  if (!restaurantId || !slug || appMetadata.restaurant_id !== restaurantId) {
    return json({ error: "INVALID_PAYLOAD" }, 422);
  }

  const menuUrl = `${PUBLIC_BASE_URL.replace(/\\/$/, "")}/r/${slug}/`;
  const pngDataUrl = await QRCode.toDataURL(menuUrl, {
    errorCorrectionLevel: "M",
    margin: 2,
    width: 960,
  });
  const base64 = pngDataUrl.split(",")[1] ?? "";
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));

  const objectPath = `${restaurantId}.png`;
  const { error: uploadError } = await serviceClient.storage
    .from("qr-codes")
    .upload(objectPath, bytes, {
      contentType: "image/png",
      cacheControl: "3600",
      upsert: true,
    });

  if (uploadError) {
    return json({ error: "UPLOAD_FAILED", detail: uploadError.message }, 500);
  }

  const publicUrl = `${SUPABASE_URL}/storage/v1/object/public/qr-codes/${objectPath}`;
  const { error: updateError } = await serviceClient
    .from("core_restaurant")
    .update({ menu_qr_code_url: publicUrl })
    .eq("id", restaurantId);

  if (updateError) {
    return json({ error: "UPDATE_FAILED", detail: updateError.message }, 500);
  }

  return json({
    ok: true,
    menu_url: menuUrl,
    qr_code_url: publicUrl,
  });
});
