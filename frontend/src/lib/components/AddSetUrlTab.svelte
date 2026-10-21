<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { ApiError } from "#lib/api/client.ts";
  import { submitUrl, listMyRipJobs, hasActiveRips, replaceRipJob, type RipJob } from "#lib/api/url_rip.ts";
  import RipJobRow from "./RipJobRow.svelte";

  let url = "";
  let busy = false;
  let error: string | null = null;
  let jobs: RipJob[] = [];
  let disclaimerDismissed = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function refresh() {
    try {
      jobs = await listMyRipJobs();
    } catch {
      /* best-effort */
    }
  }

  $: hasActive = hasActiveRips(jobs);

  onMount(async () => {
    disclaimerDismissed =
      typeof localStorage !== "undefined" &&
      localStorage.getItem("setvault.urlRipDisclaimerDismissed") === "1";
    await refresh();
    pollTimer = setInterval(() => {
      if (hasActive) void refresh();
    }, 4000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function dismissDisclaimer() {
    disclaimerDismissed = true;
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("setvault.urlRipDisclaimerDismissed", "1");
    }
  }

  async function submit() {
    error = null;
    busy = true;
    try {
      const job = await submitUrl(url);
      jobs = [job, ...jobs];
      url = "";
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "submission failed";
    } finally {
      busy = false;
    }
  }
</script>

<section class="url-tab">
  {#if !disclaimerDismissed}
    <aside class="disclaimer">
      <p>{$_("url_rip.disclaimer")}</p>
      <button type="button" on:click={dismissDisclaimer}>{$_("url_rip.dismiss")}</button>
    </aside>
  {/if}

  <form on:submit|preventDefault={submit}>
    <label>
      {$_("url_rip.url_label")}
      <input
        type="url"
        bind:value={url}
        placeholder="https://www.youtube.com/watch?v=…"
        required
        disabled={busy}
      />
    </label>
    <button type="submit" class="primary" disabled={busy || !url.trim()}>
      {busy ? $_("url_rip.submitting") : $_("url_rip.submit")}
    </button>
    {#if error}<p class="error">{error}</p>{/if}
  </form>

  {#if jobs.length > 0}
    <h3>{$_("url_rip.recent_rips")}</h3>
    <ul>
      {#each jobs as job (job.id)}
        <li><RipJobRow {job} on:retried={(e) => (jobs = replaceRipJob(jobs, e.detail.previousId, e.detail.job))} /></li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .url-tab {
    display: grid;
    gap: var(--sp-4);
    max-width: 560px;
  }
  .disclaimer {
    padding: var(--sp-3);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    display: grid;
    gap: var(--sp-2);
  }
  form { display: grid; gap: var(--sp-2); }
  label { display: grid; gap: var(--sp-1); font-size: var(--ts-sm); }
  input {
    padding: var(--sp-2);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    color: var(--text-default);
    font: inherit;
  }
  .primary {
    background: var(--accent, var(--bg-surface));
    color: var(--text-on-accent, var(--text-default));
    border: 1px solid var(--border-default);
    padding: var(--sp-2) var(--sp-4);
    border-radius: var(--r-md);
    cursor: pointer;
    justify-self: start;
  }
  .primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .error { color: #c33; font-size: var(--ts-sm); }
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: var(--sp-2);
  }
  h3 { margin: 0; font-size: var(--ts-md); }
</style>
