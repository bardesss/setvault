<script lang="ts">
  import { _ } from "svelte-i18n";
  import { uploadFile, type UploadProgress } from "#lib/api/uploads.ts";

  let file: File | null = null;
  let progress: UploadProgress | null = null;
  let error: string | null = null;
  let uploadUrl: string | null = null;
  let busy = false;

  function onSelect(ev: Event) {
    const input = ev.currentTarget as HTMLInputElement;
    file = input.files && input.files[0] ? input.files[0] : null;
    progress = null;
    error = null;
    uploadUrl = null;
  }

  function onDrop(ev: DragEvent) {
    ev.preventDefault();
    const dropped = ev.dataTransfer?.files?.[0] ?? null;
    if (dropped) {
      file = dropped;
      progress = null;
      error = null;
      uploadUrl = null;
    }
  }

  function onDragOver(ev: DragEvent) {
    ev.preventDefault();
  }

  async function start() {
    if (!file || busy) return;
    busy = true;
    error = null;
    progress = { bytesUploaded: 0, bytesTotal: file.size };
    try {
      const result = await uploadFile(file, (p) => (progress = p));
      uploadUrl = result.uploadUrl;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  $: pct =
    progress && progress.bytesTotal > 0
      ? Math.round((progress.bytesUploaded / progress.bytesTotal) * 100)
      : 0;
</script>

<div class="uploader">
  <label
    class="drop"
    on:drop={onDrop}
    on:dragover={onDragOver}
  >
    <input type="file" accept="audio/*" on:change={onSelect} />
    <span>{file ? file.name : $_("upload.drop_or_choose")}</span>
  </label>

  {#if file && !uploadUrl}
    <button type="button" on:click={start} disabled={busy}>
      {busy ? $_("upload.uploading") : $_("upload.start")}
    </button>
  {/if}

  {#if progress}
    <progress max={progress.bytesTotal} value={progress.bytesUploaded}></progress>
    <div class="pct">{pct}%</div>
  {/if}

  {#if uploadUrl}
    <div class="ok">{$_("upload.uploaded", { values: { url: uploadUrl } })}</div>
  {/if}

  {#if error}
    <div class="err">{error}</div>
  {/if}
</div>

<style>
  .uploader {
    display: grid;
    gap: var(--sp-3);
    max-width: 560px;
  }
  .drop {
    display: grid;
    place-items: center;
    padding: var(--sp-6);
    border: 2px dashed var(--border-default);
    border-radius: var(--r-md);
    background: var(--bg-surface);
    cursor: pointer;
    text-align: center;
  }
  .drop input {
    display: none;
  }
  button {
    padding: var(--sp-2) var(--sp-4);
    border-radius: var(--r-md);
    border: 1px solid var(--border-default);
    background: var(--bg-surface);
    cursor: pointer;
  }
  button[disabled] {
    opacity: 0.6;
    cursor: not-allowed;
  }
  progress {
    width: 100%;
  }
  .pct {
    font-size: var(--ts-sm);
    color: var(--text-faint);
  }
  .ok {
    color: var(--text-default);
    font-size: var(--ts-sm);
  }
  .err {
    color: var(--accent-error);
    font-size: var(--ts-sm);
  }
</style>
