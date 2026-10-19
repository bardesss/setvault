<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { api, ApiError } from "$lib/api/client";
  import {
    getSettings,
    updateSettings,
    type AdminSettings,
  } from "$lib/api/settings";

  let settings: AdminSettings | null = null;
  let order: string[] = [];
  let loading = true;
  let busy = false;
  let error: string | null = null;
  let saved = false;

  let backfill: { to_fingerprint: number; to_measure: number } | null = null;
  let backfillBusy = false;
  let backfillMsg: string | null = null;

  function msg(e: unknown, fallback: string): string {
    return e instanceof ApiError ? e.detail : fallback;
  }

  async function loadBackfill() {
    try {
      backfill = await api("/api/admin/maintenance/quality-backfill");
    } catch {
      backfill = null;
    }
  }

  onMount(async () => {
    try {
      settings = await getSettings();
      order = [...settings.quality_tiers_order];
    } catch (e) {
      error = msg(e, $_("quality.load_failed"));
    } finally {
      loading = false;
    }
    await loadBackfill();
  });

  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= order.length) return;
    const next = [...order];
    [next[i], next[j]] = [next[j], next[i]];
    order = next;
  }

  function tierName(t: string): string {
    return $_(`quality.tier_${t}`, { default: t });
  }

  async function save() {
    if (!settings) return;
    busy = true;
    error = null;
    saved = false;
    try {
      settings = await updateSettings({
        quality_tiers_order: order,
        quality_cutoff: settings.quality_cutoff,
        auto_upgrades_enabled: settings.auto_upgrades_enabled,
        upgrade_search_schedule: settings.upgrade_search_schedule,
      });
      order = [...settings.quality_tiers_order];
      saved = true;
    } catch (e) {
      error = msg(e, $_("quality.save_failed"));
    } finally {
      busy = false;
    }
  }

  async function runBackfill() {
    backfillBusy = true;
    backfillMsg = null;
    try {
      await api("/api/admin/maintenance/quality-backfill", { method: "POST" });
      backfillMsg = $_("quality.backfill_started");
      await loadBackfill();
    } catch (e) {
      backfillMsg = msg(e, $_("quality.backfill_failed"));
    } finally {
      backfillBusy = false;
    }
  }
</script>

<section class="quality">
  <header>
    <h2>{$_("quality.heading")}</h2>
    <p class="muted">{$_("quality.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if settings}
    <div class="card">
      <h3>{$_("quality.tier_order_title")}</h3>
      <p class="muted">{$_("quality.tier_order_hint")}</p>
      <ol class="tiers" data-testid="tier-order">
        {#each order as tier, i (tier)}
          <li>
            <span class="name">{tierName(tier)}</span>
            <button
              type="button"
              class="btn btn-sm"
              disabled={i === 0 || busy}
              aria-label={$_("quality.move_up", { values: { tier: tierName(tier) } })}
              on:click={() => move(i, -1)}
            >↑</button>
            <button
              type="button"
              class="btn btn-sm"
              disabled={i === order.length - 1 || busy}
              aria-label={$_("quality.move_down", { values: { tier: tierName(tier) } })}
              on:click={() => move(i, 1)}
            >↓</button>
          </li>
        {/each}
      </ol>

      <label class="row">
        <span>{$_("quality.cutoff")}</span>
        <select bind:value={settings.quality_cutoff} disabled={busy}>
          {#each order as tier (tier)}
            <option value={tier}>{tierName(tier)}</option>
          {/each}
        </select>
      </label>
      <p class="muted">{$_("quality.cutoff_hint")}</p>

      <label class="row">
        <input type="checkbox" bind:checked={settings.auto_upgrades_enabled} disabled={busy} />
        <span>{$_("quality.auto_upgrades")}</span>
      </label>

      <label class="row">
        <span>{$_("quality.upgrade_search")}</span>
        <select bind:value={settings.upgrade_search_schedule} disabled={busy}>
          <option value="daily">{$_("quality.schedule_daily")}</option>
          <option value="weekly">{$_("quality.schedule_weekly")}</option>
          <option value="off">{$_("quality.schedule_off")}</option>
        </select>
      </label>

      <div class="row">
        <button type="button" class="btn btn-primary btn-sm" disabled={busy} on:click={save}>
          {busy ? $_("quality.saving") : $_("quality.save")}
        </button>
        {#if saved}<span class="muted" role="status">{$_("quality.saved")}</span>{/if}
      </div>
    </div>

    <div class="card">
      <h3>{$_("quality.backfill_title")}</h3>
      <p class="muted">{$_("quality.backfill_hint")}</p>
      {#if backfill}
        <p data-testid="backfill-counts">
          {$_("quality.backfill_counts", {
            values: { fingerprint: backfill.to_fingerprint, measure: backfill.to_measure },
          })}
        </p>
      {/if}
      <div class="row">
        <button type="button" class="btn btn-sm" disabled={backfillBusy} on:click={runBackfill}>
          {$_("quality.backfill_run")}
        </button>
        {#if backfillMsg}<span class="muted" role="status">{backfillMsg}</span>{/if}
      </div>
    </div>
  {/if}
</section>

<style>
  .quality { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .card { display: grid; gap: var(--sp-2); justify-items: start; }
  h3 { margin: 0; }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .tiers { list-style: decimal inside; margin: 0; padding: 0; display: grid; gap: var(--sp-1); }
  .tiers li { display: flex; align-items: center; gap: var(--sp-2); }
  .tiers .name { min-width: 6rem; }
  .row { display: flex; align-items: center; gap: var(--sp-2); }
</style>
