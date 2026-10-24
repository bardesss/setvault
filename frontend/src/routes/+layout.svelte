<script lang="ts">
  import "#lib/styles/fonts.css";
  import "#lib/styles/tokens.css";
  import "#lib/styles/_breakpoints.css";
  import "#lib/styles/base.css";
  import "#lib/styles/components.css";
  import { onMount } from "svelte";
  import { browser } from "$app/env";
  import { page } from "$app/state";
  import { toStore } from "svelte/store";
  import { postStoredCap } from "#lib/stores/offline.ts";
  import { session } from "#lib/stores/session.ts";
  import { setupI18n } from "#lib/i18n/index.ts";
  import NavRail from "#lib/components/NavRail.svelte";
  import TopBar from "#lib/components/TopBar.svelte";
  import MiniPlayer from "#lib/components/MiniPlayer.svelte";
  import FullScreenPlayer from "#lib/components/FullScreenPlayer.svelte";
  import AudioHost from "#lib/components/AudioHost.svelte";
  import Toaster from "#lib/components/Toaster.svelte";

  setupI18n();

  onMount(() => {
    if (!browser || !("serviceWorker" in navigator)) return;
    // The SW persists the cap itself; re-post the stored one so a freshly
    // activated worker (or a first install) is in sync with the user setting.
    const syncCap = () => void postStoredCap();
    navigator.serviceWorker.addEventListener("controllerchange", syncCap);
    void (async () => {
      try {
        await navigator.serviceWorker.register("/service-worker.js", {
          type: "module",
        });
        await navigator.serviceWorker.ready;
        syncCap();
      } catch {
        // best-effort; offline mode just doesn't activate
      }
    })();
    return () =>
      navigator.serviceWorker.removeEventListener("controllerchange", syncCap);
  });

  export let data: { user: import("#lib/api/auth.ts").CurrentUser | null };
  $: session.set(data.user);

  // Legacy `$:` statements don't track rune state like `page`; a store does.
  const pageUrl = toStore(() => page.url);

  $: user = data.user;
  $: showShell = !!user && !$pageUrl.pathname.startsWith("/login")
                  && !$pageUrl.pathname.startsWith("/invite/")
                  && !$pageUrl.pathname.startsWith("/reset/")
                  && !$pageUrl.pathname.startsWith("/embed/");
</script>

<AudioHost />
<Toaster />
<div class="app-shell" class:no-shell={!showShell}>
  {#if showShell && user}
    <TopBar {user} />
    <NavRail {user} />
  {/if}
  <main class="main"><slot /></main>
</div>
{#if showShell}<MiniPlayer />{/if}
{#if showShell}<FullScreenPlayer />{/if}

<style>
  .app-shell {
    display: grid;
    grid-template-columns: 220px 1fr;
    grid-template-rows: auto 1fr;
    grid-template-areas:
      "topbar topbar"
      "rail main";
    min-height: 100vh;
  }
  .app-shell.no-shell {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr;
    grid-template-areas: "main";
  }
  .main { grid-area: main; min-width: 0; }
  @media (max-width: 760px) {
    .app-shell {
      grid-template-columns: 1fr;
      grid-template-areas:
        "topbar"
        "main";
    }
    .app-shell :global(.rail) { grid-area: auto; }
  }
  @media (max-width: 600px) {
    .app-shell:not(.no-shell) .main {
      padding-bottom: calc(64px + env(safe-area-inset-bottom, 0px));
    }
  }
</style>
