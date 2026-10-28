<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import * as audio from "#lib/stores/audio.ts";
  import { shouldIgnoreShortcut } from "#lib/keyboard.ts";
  import { startQueueSync } from "#lib/stores/queue-sync.ts";

  onMount(() => {
    audio.init();
    startQueueSync();
    window.addEventListener("keydown", onKey);
  });
  onDestroy(() => {
    if (typeof window !== "undefined") window.removeEventListener("keydown", onKey);
  });

  function onKey(e: KeyboardEvent): void {
    const k = e.key;
    if (shouldIgnoreShortcut(e, k)) return;
    if (k === " " || k === "k" || k === "K") { e.preventDefault(); audio.toggle(); }
    else if (k === "j" || k === "J" || k === "ArrowLeft") { e.preventDefault(); audio.seekBy(k === "ArrowLeft" ? -5 : -10); }
    else if (k === "l" || k === "L" || k === "ArrowRight") { e.preventDefault(); audio.seekBy(k === "ArrowRight" ? 5 : 10); }
    else if (k === "[") { e.preventDefault(); audio.setLoopStart(); }
    else if (k === "]") { e.preventDefault(); audio.setLoopEnd(); }
    else if (k === "\\") { e.preventDefault(); audio.clearLoop(); }
  }
</script>
