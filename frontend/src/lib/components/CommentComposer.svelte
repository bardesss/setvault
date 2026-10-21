<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";
  import { postComment } from "#lib/api/comments.ts";
  import { player } from "#lib/stores/audio.ts";

  export let slug: string;
  export let parent_id: string | null = null;
  export let flat = false;

  let body = "";
  let attachTimestamp = false;
  let busy = false;
  const dispatch = createEventDispatcher();

  async function send() {
    busy = true;
    try {
      const c = await postComment(slug, {
        body,
        parent_id,
        position_seconds: attachTimestamp ? Math.floor($player.position ?? 0) : null,
      });
      dispatch("posted", c);
      body = "";
    } finally { busy = false; }
  }
</script>

<form class="composer" class:flat on:submit|preventDefault={send}>
  <textarea
    bind:value={body}
    placeholder={$_("comments.composer_placeholder")}
    aria-label={$_("comments.composer_placeholder")}
    rows="3"
  ></textarea>
  <label class="ts">
    <input type="checkbox" bind:checked={attachTimestamp} />
    {$_("comments.attach_timestamp")}
  </label>
  <button type="submit" class="primary" disabled={busy || !body.trim()}>{$_("comments.send")}</button>
</form>

<style>
  .composer { display: grid; gap: var(--sp-2); padding: var(--sp-3);
              border: 1px solid var(--border-default); border-radius: var(--r-md); }
  .composer.flat { padding: 0; border: none; }
  textarea { font: inherit; padding: var(--sp-2); border: 1px solid var(--border-default);
             background: var(--surface-0); color: var(--text-default);
             border-radius: var(--r-sm); resize: vertical; }
  .ts { font-size: var(--ts-sm); color: var(--text-muted); display: flex; gap: var(--sp-2); align-items: center; }
  .primary { background: var(--accent); color: var(--surface-0); border: none;
             padding: var(--sp-2) var(--sp-3); border-radius: var(--r-sm); cursor: pointer; justify-self: start; }
  .primary:disabled { opacity: 0.5; }
</style>
