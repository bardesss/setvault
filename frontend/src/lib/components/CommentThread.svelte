<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { deleteComment, listComments, type Comment } from "#lib/api/comments.ts";
  import { seekInSet } from "#lib/stores/audio.ts";
  import { session } from "#lib/stores/session.ts";
  import CommentComposer from "./CommentComposer.svelte";
  import { fmtDuration } from "#lib/format.ts";

  export let slug: string;
  export let flat = false;

  $: canModerate = (c: Comment): boolean =>
    !!$session && ($session.id === c.author.id || $session.role === "admin");

  let items: Comment[] = [];
  let replyingTo: string | null = null;

  onMount(async () => { items = (await listComments(slug)).items; });

  $: topLevel = items.filter((c) => !c.parent_id);
  $: byParent = items.reduce<Record<string, Comment[]>>((acc, c) => {
    if (c.parent_id) (acc[c.parent_id] ??= []).push(c);
    return acc;
  }, {});

  async function remove(id: string) {
    await deleteComment(id);
    items = items.map((c) => c.id === id ? { ...c, deleted_at: new Date().toISOString() } : c);
  }

  function onPosted(detail: Comment) {
    items = [...items, detail];
    replyingTo = null;
  }
</script>

<section class="comments" class:flat aria-label={$_("comments.heading")}>
  {#if !flat}<h3>{$_("comments.heading")}</h3>{/if}

  <CommentComposer {slug} {flat} on:posted={(e) => onPosted(e.detail)} />

  <ul>
    {#each topLevel as c (c.id)}
      <li class:deleted={!!c.deleted_at}>
        <header>
          <span class="author">{c.author.display_name ?? c.author.username}</span>
          {#if c.position_seconds !== null}
            {@const pos = c.position_seconds}
            <button class="seek" on:click={() => void seekInSet(slug, pos)}>{fmtDuration(pos)}</button>
          {/if}
          <time>{new Date(c.created_at).toLocaleString()}</time>
        </header>
        {#if c.deleted_at}
          <p class="placeholder">{$_("comments.deleted_placeholder")}</p>
        {:else}
          {@html c.body_html}
          <footer>
            <button on:click={() => (replyingTo = c.id)}>{$_("comments.reply")}</button>
            {#if canModerate(c)}
              <button on:click={() => remove(c.id)}>{$_("comments.delete")}</button>
            {/if}
          </footer>
          {#if replyingTo === c.id}
            <CommentComposer {slug} parent_id={c.id} on:posted={(e) => onPosted(e.detail)} />
          {/if}
        {/if}
        {#if byParent[c.id]?.length}
          <ul class="replies">
            {#each byParent[c.id] as r (r.id)}
              <li class:deleted={!!r.deleted_at}>
                <header>
                  <span class="author">{r.author.display_name ?? r.author.username}</span>
                  <time>{new Date(r.created_at).toLocaleString()}</time>
                </header>
                {#if r.deleted_at}
                  <p class="placeholder">{$_("comments.deleted_placeholder")}</p>
                {:else}
                  {@html r.body_html}
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </li>
    {/each}
  </ul>
</section>

<style>
  .comments { padding: var(--sp-4); display: grid; gap: var(--sp-3); }
  .comments.flat { padding: 0; }
  h3 { margin: 0; font-size: var(--ts-lg); }
  ul { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--sp-3); }
  li { padding: var(--sp-3); border: 1px solid var(--border-default); border-radius: var(--r-md); }
  li.deleted { opacity: 0.6; }
  header { display: flex; gap: var(--sp-2); align-items: baseline; font-size: var(--ts-sm); color: var(--text-muted); }
  .author { color: var(--text-default); font-weight: 600; }
  .seek { background: none; border: 1px solid var(--border-default); border-radius: var(--r-pill);
          padding: 0 var(--sp-2); font-family: var(--font-mono); font-size: var(--ts-xs); cursor: pointer; }
  footer { display: flex; gap: var(--sp-2); margin-top: var(--sp-2); }
  footer button { background: none; border: none; color: var(--text-muted); cursor: pointer; }
  .placeholder { color: var(--text-faint); font-style: italic; }
  ul.replies { margin-top: var(--sp-2); padding-left: var(--sp-4); border-left: 2px solid var(--border-default); }
  @media (max-width: 600px) {
    .comments { padding: var(--sp-2); }
    li { padding: var(--sp-2); }
    ul.replies { padding-left: var(--sp-2); }
    footer { flex-wrap: wrap; }
    footer button { padding: var(--sp-1) var(--sp-2); min-height: 36px; }
    /* iOS Safari auto-zooms on any input < 16px font-size; prevent that on
       textareas the composer uses. */
    :global(.comments textarea) { font-size: 16px; }
  }
</style>
