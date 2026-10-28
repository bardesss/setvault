<script lang="ts">
  import { _ } from "svelte-i18n";
  import AddSetUrlTab from "#lib/components/AddSetUrlTab.svelte";
  import Uploader from "#lib/components/Uploader.svelte";
  import TabStrip from "#lib/components/TabStrip.svelte";

  let active = "upload";
  $: tabs = [
    { id: "upload", label: $_("url_rip.tab_upload") },
    { id: "url", label: $_("url_rip.tab_label") },
  ];
</script>

<svelte:head><title>{$_("sets_new.title")} - SetVault</title></svelte:head>

<section>
  <h1>{$_("sets_new.title")}</h1>

  <TabStrip {tabs} bind:active />

  {#if active === "upload"}
    <Uploader />
  {:else}
    <AddSetUrlTab />
  {/if}
</section>

<style>
  section { padding: var(--sp-6); display: grid; gap: var(--sp-4); }
</style>
