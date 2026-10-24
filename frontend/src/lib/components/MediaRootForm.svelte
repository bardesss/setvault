<script lang="ts">
  import { createEventDispatcher, onDestroy } from "svelte";
  import { _ } from "svelte-i18n";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import { errorMessage } from "#lib/api/errors.ts";
  import {
    createMediaRoot,
    patchMediaRoot,
    previewNaming,
    type MediaRoot,
    type MediaRootPatch,
    type NamingPreview,
  } from "#lib/api/media_roots.ts";

  /** null = create a new root; a root = edit it (host path is read-only). */
  export let root: MediaRoot | null = null;

  const dispatch = createEventDispatcher<{ saved: MediaRoot }>();
  const GIB = 1024 ** 3;
  const PREVIEW_DELAY_MS = 300;

  function gibText(bytes: number | null): string {
    return bytes === null ? "" : String(Math.round((bytes / GIB) * 100) / 100);
  }

  const initialQuota = gibText(root?.max_bytes ?? null);
  let name = root?.name ?? "";
  let hostPath = root?.host_path ?? "";
  let isDefault = root?.default_for_ingest ?? false;
  let enabled = root?.enabled ?? true;
  let quota = initialQuota;
  let template = root?.naming_template ?? "";

  let busy = false;
  let formError: string | null = null;
  let preview: NamingPreview | null = null;
  let previewError: string | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let seq = 0;

  function schedulePreview(t: string) {
    clearTimeout(timer);
    seq += 1;
    if (t.trim() === "") {
      preview = null;
      previewError = null;
      return;
    }
    const mine = seq;
    timer = setTimeout(async () => {
      try {
        const result = await previewNaming(t.trim());
        if (mine !== seq) return;
        preview = result;
        previewError = null;
      } catch (e) {
        if (mine !== seq) return;
        preview = null;
        previewError = errorMessage(e);
      }
    }, PREVIEW_DELAY_MS);
  }

  $: schedulePreview(template);
  onDestroy(() => clearTimeout(timer));

  /** Quota text to bytes; "" = unlimited (null); undefined = not a valid size. */
  function quotaBytes(text: string): number | null | undefined {
    const t = text.trim();
    if (t === "") return null;
    const n = Number(t);
    if (!Number.isFinite(n) || n < 0) return undefined;
    return Math.round(n * GIB);
  }

  async function save() {
    formError = null;
    const bytes = quotaBytes(quota);
    if (bytes === undefined) {
      formError = $_("admin.storage.quota_invalid");
      return;
    }
    const tpl = template.trim() === "" ? null : template.trim();
    busy = true;
    try {
      let saved: MediaRoot;
      if (root === null) {
        saved = await createMediaRoot({
          name: name.trim(),
          host_path: hostPath.trim(),
          default_for_ingest: isDefault,
          max_bytes: bytes,
          naming_template: tpl,
        });
      } else {
        const patch: MediaRootPatch = {};
        if (name.trim() !== root.name) patch.name = name.trim();
        if (enabled !== root.enabled) patch.enabled = enabled;
        if (isDefault !== root.default_for_ingest) patch.default_for_ingest = isDefault;
        if (quota.trim() !== initialQuota) patch.max_bytes = bytes;
        if (tpl !== root.naming_template) patch.naming_template = tpl;
        saved = Object.keys(patch).length > 0 ? await patchMediaRoot(root.id, patch) : root;
      }
      dispatch("saved", saved);
    } catch (e) {
      formError = errorMessage(e);
    } finally {
      busy = false;
    }
  }
</script>

<AdminForm on:submit={save}>
  {#if formError}
    <p class="admin-msg is-error" role="alert" data-testid="root-form-error">{formError}</p>
  {/if}
  <label class="admin-field">
    <span>{$_("admin.storage.f_name")}</span>
    <input type="text" bind:value={name} required maxlength="80" />
  </label>
  <label class="admin-field">
    <span>{$_("admin.storage.f_path")}</span>
    {#if root === null}
      <input type="text" class="mono" bind:value={hostPath} required />
    {:else}
      <input type="text" class="mono" value={hostPath} readonly />
      <small class="hint">{$_("admin.storage.path_fixed")}</small>
    {/if}
  </label>
  {#if root !== null}
    <label class="admin-field inline">
      <input type="checkbox" bind:checked={enabled} />
      <span>{$_("admin.storage.f_enabled")}</span>
    </label>
  {/if}
  <label class="admin-field inline">
    <input type="checkbox" bind:checked={isDefault} />
    <span>{$_("admin.storage.f_default")}</span>
  </label>
  <label class="admin-field">
    <span>{$_("admin.storage.f_quota")}</span>
    <input type="text" inputmode="decimal" placeholder={$_("admin.storage.unlimited")} bind:value={quota} />
  </label>
  <label class="admin-field">
    <span>{$_("admin.storage.f_template")}</span>
    <input
      type="text"
      class="mono"
      placeholder={"{Artist}/{Slug}.{Ext}"}
      bind:value={template}
      maxlength="255"
    />
    <small class="hint">{$_("admin.storage.template_hint")}</small>
  </label>

  {#if previewError}
    <p class="admin-msg is-error" role="alert">{previewError}</p>
  {/if}
  {#if preview}
    <div class="preview" data-testid="naming-preview">
      {#each preview.errors as err}
        <p class="admin-msg is-error" role="alert" data-testid="naming-error">{err}</p>
      {/each}
      {#if preview.warn_no_unique_token}
        <p class="admin-msg warn" data-testid="naming-warn">{$_("admin.storage.no_unique_token")}</p>
      {/if}
      {#if preview.samples.length > 0}
        <p class="hint">{$_("admin.storage.preview_title")}</p>
        <ul>
          {#each preview.samples as s}
            <li class="mono" data-testid="naming-sample">{s}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <svelte:fragment slot="actions">
    <button type="submit" class="btn btn-primary" disabled={busy}>
      {$_("admin.storage.save")}
    </button>
  </svelte:fragment>
</AdminForm>

<style>
  .hint { color: var(--text-faint); margin: 0; font-size: var(--ts-sm); }
  .warn { color: var(--text-muted); }
  .preview ul { margin: 0; padding-left: var(--sp-4); display: grid; gap: var(--sp-1); }
  .mono { font-family: var(--font-mono); font-size: var(--ts-sm); }
</style>
