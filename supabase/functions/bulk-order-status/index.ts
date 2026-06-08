import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

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

  const body = await request.json().catch(() => null);
  const orderId = String(body?.order_id ?? "").trim();
  const action = String(body?.action ?? "").trim().toUpperCase();

  if (!orderId || !["START_ALL", "COMPLETE_ALL"].includes(action)) {
    return json({ error: "INVALID_PAYLOAD" }, 422);
  }

  const appMetadata = user.app_metadata ?? {};
  const permissions = appMetadata.permissions ?? {};
  const canBulkUpdate = appMetadata.role === "OWNER" ||
    (permissions.allow_order_completion && permissions.allow_view_all_orders);

  if (!canBulkUpdate) {
    return json({ error: "FORBIDDEN" }, 403);
  }

  const { data, error } = await serviceClient.rpc("bulk_update_order_workflow", {
    p_order_id: orderId,
    p_actor_user_id: user.id,
    p_action: action,
    p_restaurant_id: appMetadata.restaurant_id ?? null,
  });

  if (error) {
    return json({ error: "RPC_ERROR", detail: error.message }, 409);
  }

  return json({
    ok: true,
    order_id: orderId,
    result: data,
  });
});
