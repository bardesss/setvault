<script lang="ts">
  import { _, locale } from "svelte-i18n";
  import { patchSet, type SetDetail } from "$lib/api/sets";
  import { ApiError } from "$lib/api/client";

  export let set: SetDetail;

  let busy = false;
  let error: string | null = null;

  $: history = set.upgrade_history ?? [];

  function fmt(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString($locale ?? undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return iso;
    }
  }

  async function toggle(ev: Event) {
    const target = ev.currentTarget as HTMLInputElement;
    const next = target.checked;
    busy = true;
    error = null;
    try {
      const r = await patchSet(set.slug, { upgrades_enabled: next });
      set.upgrades_enabled = r.upgrades_enabled;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "failed";
      target.checked = set.upgrades_enabled;
    } finally {
      busy = false;
    }
  }
</script>

<div class="set-quality" data-testid="set-quality">
  <p class="quality-line" data-testid="set-quality-line">
    {#if set.quality}
      {$_("set.quality.label", { values: { label: set.quality.label } })}
    {:else}
      {$_("set.quality.unknown")}
    {/if}
  </p>
  <label class="upgrade-toggle">
    <input
      type="checkbox"
      data-testid="upgrades-toggle"
      checked={set.upgrades_enabled}
      on:change={toggle}
      disabled={busy}
    />
    <span>{$_("set.upgrades.toggle")}</span>
  </label>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if history.length > 0}
    <ul class="upgrade-history" data-testid="upgrade-history">
      {#each history as h (h.created_at)}
        <li>
          {$_("set.upgrades.history_line", {
            values: { date: fmt(h.created_at), from: h.from_label, to: h.to_label },
          })}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .set-quality {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin-top: var(--sp-3);
    font-size: var(--ts-sm);
    color: var(--text-faint);
  }
  .quality-line {
    margin: 0;
    color: var(--text-default);
  }
  .upgrade-toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-2);
    cursor: pointer;
  }
  .upgrade-history {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
    overflow-wrap: anywhere;
  }
  .error {
    color: #c33;
    margin: 0;
  }
</style>
