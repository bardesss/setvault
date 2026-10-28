<script lang="ts">
  import { _ } from "svelte-i18n";
  import TabStrip from "./TabStrip.svelte";
  import CommentThread from "./CommentThread.svelte";
  import BookmarkButton from "./BookmarkButton.svelte";
  import PrivateNotesPanel from "./PrivateNotesPanel.svelte";

  export let slug: string;

  // Honest-now tabs: the three engagement surfaces that actually exist.
  // (Mockup's About/Artist/Activity tabs are deferred to a later phase.)
  let active = "comments";
  $: tabs = [
    { id: "comments", label: $_("panel.comments") },
    { id: "bookmarks", label: $_("panel.bookmarks") },
    { id: "notes", label: $_("panel.notes") },
  ];
</script>

<aside class="side-panel" aria-label={$_("panel.label")}>
  <div class="side-panel-tabs">
    <TabStrip {tabs} bind:active />
  </div>
  <div class="side-content">
    {#if active === "comments"}
      <div class="side-section" role="tabpanel" aria-label={$_("panel.comments")}>
        <CommentThread {slug} flat />
      </div>
    {:else if active === "bookmarks"}
      <div class="side-section" role="tabpanel" aria-label={$_("panel.bookmarks")}>
        <h4>{$_("panel.your_bookmarks")}</h4>
        <BookmarkButton {slug} flat />
      </div>
    {:else if active === "notes"}
      <div class="side-section" role="tabpanel" aria-label={$_("panel.notes")}>
        <h4>{$_("notes.heading")}</h4>
        <PrivateNotesPanel {slug} flat />
      </div>
    {/if}
  </div>
</aside>
