<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";
  import { acceptImport, importTracklist, type ImportJob } from "#lib/api/tracklist.ts";
  import { ApiError } from "#lib/api/client.ts";
  import { setEntries } from "#lib/stores/tracklist.ts";

  export let slug: string;

  type Tab = "paste" | "url_1001tl" | "ocr";
  let tab: Tab = "paste";
  let busy = false;
  let error: string | null = null;
  let pasteText = "";
  let url = "";
  let imageFile: File | null = null;
  let job: ImportJob | null = null;
  let accepted = new Set<number>();
  const dispatch = createEventDispatcher();

  async function runImport() {
    busy = true;
    error = null;
    try {
      let payload: Record<string, unknown>;
      if (tab === "paste") {
        payload = { text: pasteText };
      } else if (tab === "url_1001tl") {
        payload = { url };
      } else {
        if (!imageFile) {
          error = $_("tracklist.import_choose_image");
          busy = false;
          return;
        }
        const b64 = await fileToB64(imageFile);
        payload = { image_b64: b64 };
      }
      job = await importTracklist(slug, tab, payload);
      if (job.status === "failed") {
        error = job.error ?? "import failed";
      } else if (job.status === "succeeded") {
        accepted = new Set(job.parsed.map((_p, i) => i));
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        error = $_("tracklist.import_disabled");
      } else {
        error = e instanceof Error ? e.message : "error";
      }
    } finally {
      busy = false;
    }
  }

  function fileToB64(f: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = r.result as string;
        resolve(s.split(",")[1] ?? "");
      };
      r.onerror = reject;
      r.readAsDataURL(f);
    });
  }

  function onFileChange(e: Event) {
    imageFile = (e.target as HTMLInputElement).files?.[0] ?? null;
  }

  function toggle(i: number) {
    const next = new Set(accepted);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    accepted = next;
  }

  async function confirmAccept() {
    if (!job) return;
    const { entries } = await acceptImport(slug, job.id, Array.from(accepted));
    setEntries(entries);
    dispatch("close");
  }

  function fmt(s: number): string {
    const m = Math.floor(s / 60);
    const ss = s % 60;
    return `${m}:${String(ss).padStart(2, "0")}`;
  }
</script>

<div
  class="backdrop"
  on:click={() => dispatch("close")}
  role="presentation"
></div>
<section class="modal" role="dialog" aria-label={$_("tracklist.import")}>
  <header>
    <h3>{$_("tracklist.import")}</h3>
    <button on:click={() => dispatch("close")} aria-label="close">✕</button>
  </header>
  <nav class="tabs">
    <button class:active={tab === "paste"} on:click={() => (tab = "paste")}>
      {$_("tracklist.tab_paste")}
    </button>
    <button class:active={tab === "url_1001tl"} on:click={() => (tab = "url_1001tl")}>
      {$_("tracklist.tab_url")}
    </button>
    <button class:active={tab === "ocr"} on:click={() => (tab = "ocr")}>
      {$_("tracklist.tab_ocr")}
    </button>
  </nav>

  {#if !job}
    {#if tab === "paste"}
      <textarea bind:value={pasteText} placeholder={$_("tracklist.paste_placeholder")} rows="10"
      ></textarea>
    {:else if tab === "url_1001tl"}
      <p class="warning">{$_("tracklist.import_1001tl_warning")}</p>
      <input type="url" bind:value={url} placeholder="https://www.1001tracklists.com/..." />
    {:else}
      <p class="warning">{$_("tracklist.import_ocr_warning")}</p>
      <input type="file" accept="image/*" on:change={onFileChange} />
    {/if}
    {#if error}<p class="error">{error}</p>{/if}
    <footer>
      <button on:click={() => dispatch("close")}>{$_("tracklist.cancel")}</button>
      <button class="primary" on:click={runImport} disabled={busy}>
        {busy ? "…" : $_("tracklist.parse")}
      </button>
    </footer>
  {:else}
    <p>{$_("tracklist.import_review", { values: { count: job.parsed.length } })}</p>
    <ul class="preview">
      {#each job.parsed as p, i (i)}
        <li>
          <input type="checkbox" checked={accepted.has(i)} on:change={() => toggle(i)} />
          <span class="t mono">{fmt(p.start_seconds)}</span>
          <span>{p.raw_label}</span>
        </li>
      {/each}
    </ul>
    <footer>
      <button on:click={() => (job = null)}>{$_("tracklist.back")}</button>
      <button class="primary" on:click={confirmAccept}>
        {$_("tracklist.accept_selected", { values: { count: accepted.size } })}
      </button>
    </footer>
  {/if}
</section>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: var(--z-overlay); }
  .modal { position: fixed; top: 10vh; left: 50%; transform: translateX(-50%);
           width: min(640px, 92vw); max-height: 80vh; overflow-y: auto;
           background: var(--bg-elevated); padding: var(--sp-6); border-radius: var(--r-md);
           box-shadow: var(--shadow-lg);
           z-index: var(--z-modal); display: grid; gap: var(--sp-3); }
  header { display: flex; justify-content: space-between; align-items: center; }
  .tabs { display: flex; gap: var(--sp-2); }
  .tabs button { background: none; border: 1px solid var(--border-default); border-radius: var(--r-sm);
                 padding: var(--sp-2) var(--sp-3); cursor: pointer; color: var(--text-muted); }
  .tabs button.active { color: var(--text-default); background: var(--bg-hover); }
  textarea, input[type=url] { padding: var(--sp-2); border: 1px solid var(--border-default);
                              border-radius: var(--r-sm); background: var(--bg-input);
                              color: var(--text-default); font: inherit; width: 100%;
                              box-sizing: border-box; }
  .warning { color: var(--accent-warning); }
  .error { color: var(--accent-error); }
  .preview { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--sp-1);
             max-height: 50vh; overflow-y: auto; }
  .preview li { display: grid; grid-template-columns: auto auto 1fr; gap: var(--sp-2);
                align-items: center; }
  .t { font-family: var(--font-mono); color: var(--text-muted); }
  footer { display: flex; justify-content: space-between; gap: var(--sp-2); }
  .primary { background: var(--accent); color: var(--text-on-accent); border: none;
             padding: var(--sp-2) var(--sp-3); border-radius: var(--r-sm); cursor: pointer; }
</style>
