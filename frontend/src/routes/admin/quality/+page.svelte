<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { _, locale } from "svelte-i18n";
  import { api, ApiError } from "#lib/api/client.ts";
  import {
    getSettings,
    regainLibrary,
    updateSettings,
    type AdminSettings,
  } from "#lib/api/settings.ts";
  import { fmtLocalDateTime } from "#lib/format.ts";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import { toast } from "#lib/stores/toast.ts";

  const TIER_KEYS: Record<string, string> = {
    lossless: "admin.quality.tier_lossless",
    high: "admin.quality.tier_high",
    good: "admin.quality.tier_good",
    ok: "admin.quality.tier_ok",
    low: "admin.quality.tier_low",
  };

  let settings: AdminSettings | null = null;
  let order: string[] = [];
  let loading = true;
  let busy = false;
  let error: string | null = null;
  let saved = false;

  interface BackfillDryRun {
    to_fingerprint: number;
    to_measure: number;
    // The last duplicate scan (run in the worker); null until one has run.
    duplicate_pairs: number | null;
    duplicate_pairs_complete: boolean | null;
    scanned_at: string | null;
    failed?: number;
  }

  let backfill: BackfillDryRun | null = null;
  let backfillLoading = false;
  let backfillBusy = false;
  let backfillMsg: string | null = null;
  let cleanup = false;
  let retryFailed = false;
  let scanBusy = false;
  let scanMsg: string | null = null;
  let scanPoll: ReturnType<typeof setTimeout> | null = null;
  // How long to keep checking for the queued scan's result.
  const SCAN_POLL_MS = 3000;
  const SCAN_POLL_TRIES = 40;

  function msg(e: unknown, fallback: string): string {
    return e instanceof ApiError ? e.detail : fallback;
  }

  async function loadBackfill() {
    backfillLoading = true;
    try {
      backfill = await api("/api/admin/maintenance/quality-backfill");
    } catch {
      backfill = null;
    } finally {
      backfillLoading = false;
    }
  }

  function pairsText(b: BackfillDryRun): string {
    if (b.duplicate_pairs === null) return $_("admin.quality.scan.never");
    const values = { count: b.duplicate_pairs };
    return b.duplicate_pairs_complete
      ? $_("admin.quality.pairs_found", { values })
      : $_("admin.quality.pairs_found_partial", { values });
  }

  onMount(async () => {
    try {
      settings = await getSettings();
      order = [...settings.quality_tiers_order];
      const target = settings.loudness_target_lufs ?? null;
      loudnessText = target === null ? "" : String(target);
    } catch (e) {
      error = msg(e, $_("admin.quality.load_failed"));
    } finally {
      loading = false;
    }
    await loadBackfill();
  });

  onDestroy(() => {
    if (scanPoll) clearTimeout(scanPoll);
  });

  /** Queue a fresh duplicate scan in the worker, then check back until its
   * result replaces the cached one. */
  async function refreshScan() {
    scanBusy = true;
    scanMsg = null;
    const before = backfill?.scanned_at ?? null;
    try {
      await api("/api/admin/maintenance/quality-backfill/scan", { method: "POST" });
    } catch (e) {
      scanMsg = msg(e, $_("admin.quality.scan.failed"));
      scanBusy = false;
      return;
    }
    scanMsg = $_("admin.quality.scan.queued");
    let tries = 0;
    const check = async () => {
      scanPoll = null;
      await loadBackfill();
      if ((backfill?.scanned_at ?? null) !== before) {
        scanMsg = null;
        scanBusy = false;
      } else if (++tries < SCAN_POLL_TRIES) {
        scanPoll = setTimeout(check, SCAN_POLL_MS);
      } else {
        scanMsg = $_("admin.quality.scan.still_running");
        scanBusy = false;
      }
    };
    scanPoll = setTimeout(check, SCAN_POLL_MS);
  }

  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= order.length) return;
    const next = [...order];
    [next[i], next[j]] = [next[j], next[i]];
    order = next;
  }

  function tierName(t: string): string {
    return TIER_KEYS[t] ? $_(TIER_KEYS[t]) : t;
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
      error = msg(e, $_("admin.common.save_failed"));
    } finally {
      busy = false;
    }
  }

  // Loudness target. Text field so "empty" is a real value (null = off).
  let loudnessText = "";
  let loudnessBusy = false;
  let loudnessError: string | null = null;
  let confirmRegain = false;
  let regainBusy = false;

  function parseLoudness(text: string): number | null | undefined {
    const t = text.trim();
    if (t === "") return null;
    const n = Number(t.replace(",", "."));
    if (!Number.isFinite(n) || n < -30 || n > -5) return undefined;
    return n;
  }

  async function saveLoudness() {
    const value = parseLoudness(loudnessText);
    if (value === undefined) {
      loudnessError = $_("admin.quality.loudness.invalid");
      return;
    }
    loudnessBusy = true;
    loudnessError = null;
    try {
      const s = await updateSettings({ loudness_target_lufs: value });
      settings = settings ? { ...settings, loudness_target_lufs: s.loudness_target_lufs } : s;
      loudnessText = s.loudness_target_lufs === null ? "" : String(s.loudness_target_lufs);
      toast.success($_("admin.quality.loudness.saved"));
    } catch (e) {
      loudnessError = msg(e, $_("admin.common.save_failed"));
    } finally {
      loudnessBusy = false;
    }
  }

  async function reapplyLoudness() {
    confirmRegain = false;
    regainBusy = true;
    try {
      await regainLibrary();
      toast.success($_("admin.quality.loudness.queued"));
    } catch (e) {
      toast.error(msg(e, $_("admin.quality.loudness.failed")));
    } finally {
      regainBusy = false;
    }
  }

  async function runBackfill() {
    backfillBusy = true;
    backfillMsg = null;
    try {
      const r = await api<Partial<BackfillDryRun>>("/api/admin/maintenance/quality-backfill", {
        method: "POST",
        body: JSON.stringify({ cleanup, retry_failed: retryFailed }),
      });
      if (r && (r as { status?: string }).status === "already_running") {
        backfillMsg = $_("admin.quality.backfill_already_running");
        return;
      }
      backfillMsg = cleanup
        ? $_("admin.quality.backfill_started_cleanup")
        : $_("admin.quality.backfill_started");
      // The response carries fresh fingerprint/measure counts; the duplicate
      // pair count is a slow scan and isn't re-run here.
      if (backfill && r && typeof r.to_fingerprint === "number" && typeof r.to_measure === "number") {
        backfill = {
          ...backfill,
          to_fingerprint: r.to_fingerprint,
          to_measure: r.to_measure,
          failed: typeof r.failed === "number" ? r.failed : backfill.failed,
        };
      }
      retryFailed = false;
    } catch (e) {
      backfillMsg = msg(e, $_("admin.quality.backfill_failed"));
    } finally {
      backfillBusy = false;
    }
  }
</script>

<section class="quality">
  <header>
    <h2>{$_("admin.quality.title")}</h2>
    <p class="muted">{$_("admin.quality.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="muted">{$_("common.loading")}</p>
  {:else if settings}
    <div class="card">
      <h3>{$_("admin.quality.order_title")}</h3>
      <p class="muted">{$_("admin.quality.order_help")}</p>
      <ol class="tiers" data-testid="tier-order">
        {#each order as tier, i (tier)}
          <li>
            <span class="name">{tierName(tier)}</span>
            <button
              type="button"
              class="btn btn-sm"
              disabled={i === 0 || busy}
              aria-label={$_("admin.quality.move_up", { values: { tier: tierName(tier) } })}
              on:click={() => move(i, -1)}
            >↑</button>
            <button
              type="button"
              class="btn btn-sm"
              disabled={i === order.length - 1 || busy}
              aria-label={$_("admin.quality.move_down", { values: { tier: tierName(tier) } })}
              on:click={() => move(i, 1)}
            >↓</button>
          </li>
        {/each}
      </ol>

      <label class="row">
        <span>{$_("admin.quality.cutoff")}</span>
        <select bind:value={settings.quality_cutoff} disabled={busy}>
          {#each order as tier (tier)}
            <option value={tier}>{tierName(tier)}</option>
          {/each}
        </select>
      </label>
      <p class="muted">{$_("admin.quality.cutoff_help")}</p>

      <label class="row">
        <input type="checkbox" bind:checked={settings.auto_upgrades_enabled} disabled={busy} />
        <span>{$_("admin.quality.auto_upgrades")}</span>
      </label>

      <label class="row">
        <span>{$_("admin.quality.upgrade_search")}</span>
        <select bind:value={settings.upgrade_search_schedule} disabled={busy}>
          <option value="daily">{$_("admin.quality.schedule_daily")}</option>
          <option value="weekly">{$_("admin.quality.schedule_weekly")}</option>
          <option value="off">{$_("admin.quality.schedule_off")}</option>
        </select>
      </label>

      <div class="row">
        <button type="button" class="btn btn-primary btn-sm" disabled={busy} on:click={save}>
          {busy ? $_("admin.common.saving") : $_("admin.common.save")}
        </button>
        {#if saved}<span class="muted" role="status">{$_("admin.common.saved")}</span>{/if}
      </div>
    </div>

    <div class="card">
      <h3>{$_("admin.quality.loudness.title")}</h3>
      <label class="row">
        <span>{$_("admin.quality.loudness.target")}</span>
        <input
          type="text"
          inputmode="decimal"
          size="6"
          data-testid="loudness-target"
          bind:value={loudnessText}
          disabled={loudnessBusy}
          aria-describedby="loudness-help"
        />
        {#if loudnessText.trim() === ""}
          <span class="muted" data-testid="loudness-off">{$_("admin.quality.loudness.off")}</span>
        {/if}
      </label>
      <p class="muted" id="loudness-help">{$_("admin.quality.loudness.help")}</p>
      {#if loudnessError}<p class="admin-msg is-error" role="alert">{loudnessError}</p>{/if}
      <div class="row">
        <button
          type="button"
          class="btn btn-primary btn-sm"
          disabled={loudnessBusy}
          data-testid="loudness-save"
          on:click={saveLoudness}
        >{$_("admin.quality.loudness.set_target")}</button>
      </div>
      <p class="muted">{$_("admin.quality.loudness.reapply_help")}</p>
      <div class="row">
        <button
          type="button"
          class="btn btn-sm"
          disabled={regainBusy}
          on:click={() => (confirmRegain = true)}
        >{$_("admin.quality.loudness.reapply")}</button>
      </div>
    </div>

    <div class="card">
      <h3>{$_("admin.quality.backfill_title")}</h3>
      <p class="muted">{$_("admin.quality.backfill_intro")}</p>
      {#if backfillLoading && !backfill}
        <p class="muted">{$_("admin.quality.counting")}</p>
      {:else if backfill}
        <p data-testid="backfill-counts">
          {$_("admin.quality.backfill_counts", { values: { fingerprint: backfill.to_fingerprint, measure: backfill.to_measure } })}
        </p>
        {#if (backfill.failed ?? 0) > 0}
          <p data-testid="backfill-failed">
            {$_("admin.quality.backfill_failed_earlier", { values: { count: backfill.failed ?? 0 } })}
          </p>
        {/if}
        <p data-testid="backfill-pairs">{pairsText(backfill)}</p>
      {/if}
      <div class="row">
        {#if backfill?.scanned_at}
          <span class="muted" data-testid="backfill-scanned-at">
            {$_("admin.quality.scan.last_scanned", {
              values: { when: fmtLocalDateTime(backfill.scanned_at, $locale) },
            })}
          </span>
        {/if}
        <button type="button" class="btn btn-sm" disabled={scanBusy} on:click={refreshScan}>
          {scanBusy ? $_("admin.quality.scan.refreshing") : $_("admin.quality.scan.refresh")}
        </button>
        {#if scanMsg}<span class="muted" role="status">{scanMsg}</span>{/if}
      </div>
      <label class="row">
        <input type="checkbox" bind:checked={cleanup} disabled={backfillBusy} />
        <span>{$_("admin.quality.cleanup")}</span>
      </label>
      {#if (backfill?.failed ?? 0) > 0}
        <label class="row">
          <input type="checkbox" bind:checked={retryFailed} disabled={backfillBusy} />
          <span>{$_("admin.quality.retry_failed")}</span>
        </label>
        <p class="muted">{$_("admin.quality.retry_help")}</p>
      {/if}
      <p class="muted">{$_("admin.quality.cleanup_help")}</p>
      <div class="row">
        <button type="button" class="btn btn-sm" disabled={backfillBusy} on:click={runBackfill}>
          {$_("admin.quality.run_backfill")}
        </button>
        {#if backfillMsg}<span class="muted" role="status">{backfillMsg}</span>{/if}
      </div>
    </div>
  {/if}
</section>

<ConfirmDialog
  open={confirmRegain}
  title={$_("admin.quality.loudness.confirm_title")}
  message={$_("admin.quality.loudness.confirm_message")}
  confirmLabel={$_("admin.quality.loudness.confirm_label")}
  on:confirm={reapplyLoudness}
  on:cancel={() => (confirmRegain = false)}
/>

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
