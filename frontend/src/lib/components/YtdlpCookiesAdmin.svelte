<script lang="ts">
  import { onMount } from "svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/format.ts";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import StatusBlock from "#lib/components/StatusBlock.svelte";
  import { ApiError } from "#lib/api/client.ts";
  import {
    getYtdlpCookies,
    removeYtdlpCookies,
    uploadYtdlpCookies,
    type YtdlpCookiesStatus,
  } from "#lib/api/ytdlp_cookies.ts";
  import { toast } from "#lib/stores/toast.ts";

  let status: YtdlpCookiesStatus | null = null;
  let busy = false;
  let errorMsg: string | null = null;
  let confirmRemove = false;
  let fileInput: HTMLInputElement;

  function errText(e: unknown): string {
    if (e instanceof ApiError) return e.detail;
    return e instanceof Error ? e.message : "failed";
  }

  onMount(async () => {
    try {
      status = await getYtdlpCookies();
    } catch (e) {
      errorMsg = errText(e);
    }
  });

  async function onFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    busy = true;
    errorMsg = null;
    try {
      status = await uploadYtdlpCookies(await file.text());
      toast.success($_("sources.cookies.uploaded"));
    } catch (e) {
      errorMsg = errText(e);
    } finally {
      busy = false;
    }
  }

  async function remove() {
    confirmRemove = false;
    busy = true;
    errorMsg = null;
    try {
      await removeYtdlpCookies();
      status = { set: false, uploaded_at: null, youtube_cookies: 0 };
      toast.success($_("sources.cookies.removed"));
    } catch (e) {
      errorMsg = errText(e);
    } finally {
      busy = false;
    }
  }
</script>

<h2>{$_("sources.cookies.title")}</h2>

<StatusBlock>
  <p class="hint">{$_("sources.cookies.intro")}</p>

  {#if status}
    <p class="status" data-testid="cookies-status" role="status">
      {#if status.set}
        {$_("sources.cookies.status_set", {
          values: {
            count: status.youtube_cookies,
            when: status.uploaded_at ? fmtLocalDateTime(status.uploaded_at, $locale) : "–",
          },
        })}
      {:else}
        {$_("sources.cookies.status_unset")}
      {/if}
    </p>
  {/if}

  {#if errorMsg}
    <p class="admin-msg is-error" role="alert">{errorMsg}</p>
  {/if}

  <input
    bind:this={fileInput}
    type="file"
    accept=".txt,text/plain"
    class="sr-only"
    aria-label={$_("sources.cookies.file_label")}
    data-testid="cookies-file"
    on:change={onFile}
  />
  <div class="actions">
    <button type="button" class="btn" disabled={busy} on:click={() => fileInput.click()}>
      {status?.set ? $_("sources.cookies.replace") : $_("sources.cookies.upload")}
    </button>
    {#if status?.set}
      <button
        type="button"
        class="btn btn-danger"
        disabled={busy}
        on:click={() => (confirmRemove = true)}
      >
        {$_("sources.cookies.remove")}
      </button>
    {/if}
  </div>

  <ul class="hint help">
    <li>{$_("sources.cookies.help_export")}</li>
    <li>{$_("sources.cookies.help_account")}</li>
    <li>{$_("sources.cookies.help_expire")}</li>
  </ul>
</StatusBlock>

<ConfirmDialog
  open={confirmRemove}
  title={$_("sources.cookies.remove_title")}
  message={$_("sources.cookies.remove_message")}
  confirmLabel={$_("sources.cookies.remove")}
  danger
  on:confirm={remove}
  on:cancel={() => (confirmRemove = false)}
/>

<style>
  .hint { color: var(--text-faint); margin: 0; font-size: var(--ts-sm); }
  .help { padding-left: var(--sp-4); display: grid; gap: var(--sp-1); }
  .status { margin: 0; font-weight: 600; }
  .actions { display: flex; gap: var(--sp-2); }
</style>
