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

<svelte:head><title>New set - SetVault</title></svelte:head>

<section>
  <h1>New set</h1>

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
