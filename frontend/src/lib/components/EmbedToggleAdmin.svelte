<script lang="ts">
  import { _ } from "svelte-i18n";
  import { api, ApiError } from "#lib/api/client.ts";

  export let slug: string;
  export let allowed: boolean;

  let busy = false;
  let error: string | null = null;

  async function toggle(ev: Event) {
    const target = ev.currentTarget as HTMLInputElement;
    const next = target.checked;
    busy = true;
    error = null;
    try {
      const r = await api<{ slug: string; embed_allowed: boolean }>(
        `/api/sets/${encodeURIComponent(slug)}/embed`,
        {
          method: "PATCH",
          body: JSON.stringify({ allowed: next }),
        },
      );
      allowed = r.embed_allowed;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("common.failed");
      // Revert checkbox to actual server state
      target.checked = allowed;
    } finally {
      busy = false;
    }
  }
</script>

<label class="embed-toggle">
  <input
    type="checkbox"
    checked={allowed}
    on:change={toggle}
    disabled={busy}
  />
  <span>{$_("embed.allow_public")}</span>
</label>
{#if error}<p class="error">{error}</p>{/if}

<style>
  .embed-toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-2);
    font-size: var(--ts-sm);
    color: var(--text-faint);
    cursor: pointer;
  }
  .error { color: var(--accent-error); font-size: var(--ts-sm); margin: 0; }
</style>
