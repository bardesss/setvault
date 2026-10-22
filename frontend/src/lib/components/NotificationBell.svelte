<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import {
    listNotifications,
    markRead,
    readAll,
    type InAppNotification,
  } from "#lib/api/notifications.ts";

  let items: InAppNotification[] = [];
  let unread = 0;
  let open = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function refresh() {
    try {
      const data = await listNotifications();
      items = data.items;
      unread = data.unread_count;
    } catch {
      /* best-effort */
    }
  }

  onMount(() => {
    void refresh();
    pollTimer = setInterval(() => void refresh(), 60_000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  async function toggle(): Promise<void> {
    open = !open;
    if (open) await refresh();
  }

  type NotifPayload = {
    set_slug?: string;
    set_title?: string;
    from_label?: string;
    to_label?: string;
    author_username?: string;
    excerpt?: string;
    monitor_label?: string;
    auto_ingested?: number;
    pending_review?: number;
    fingerprinted?: number;
    measured?: number;
    merged?: number;
    skipped?: number;
    errors?: number;
  };

  function getPayload(n: InAppNotification): NotifPayload {
    return n.payload as NotifPayload;
  }

  async function clickItem(n: InAppNotification) {
    try {
      await markRead(n.id);
    } catch {
      /* ignore — refresh on next poll */
    }
    unread = Math.max(0, unread - (n.read_at ? 0 : 1));
    items = items.map((x) =>
      x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x,
    );
    if (n.kind === "discovery") {
      location.href = "/discoveries";
      return;
    }
    if (n.kind === "maintenance") {
      // Skipped pairs wait on the Duplicates page.
      location.href = (getPayload(n).skipped ?? 0) > 0 ? "/admin/duplicates" : "/admin/quality";
      return;
    }
    const slug = getPayload(n).set_slug;
    if (slug) location.href = `/sets/${slug}`;
  }

  async function clickReadAll() {
    await readAll();
    await refresh();
  }
</script>

<div class="bell">
  <button class="trigger" on:click={toggle} aria-label={$_("notifications.title")}>
    🔔
    {#if unread > 0}<span class="count">{unread}</span>{/if}
  </button>
  {#if open}
    <div class="panel" role="dialog">
      <header>
        <strong>{$_("notifications.title")}</strong>
        <button class="link" on:click={clickReadAll}>{$_("notifications.mark_all_read")}</button>
      </header>
      <ul>
        {#each items.slice(0, 10) as n (n.id)}
          {@const payload = getPayload(n)}
          <li class:unread={!n.read_at}>
            <button class="item" on:click={() => clickItem(n)}>
              {#if n.kind === "discovery"}
                <span>{$_("notifications.discovery_summary")} {payload.monitor_label ?? ""}</span>
              {:else if n.kind === "maintenance"}
                <span>
                  {$_("notifications.maintenance_summary", {
                    values: {
                      fingerprinted: payload.fingerprinted ?? 0,
                      measured: payload.measured ?? 0,
                      merged: payload.merged ?? 0,
                      skipped: payload.skipped ?? 0,
                      errors: payload.errors ?? 0,
                    },
                  })}
                </span>
              {:else if n.kind === "set_upgraded"}
                <span>
                  {#if !payload.set_title || !payload.from_label || !payload.to_label}
                    {$_("notifications.set_upgraded_generic")}
                  {:else}
                    {$_("notifications.set_upgraded", {
                      values: {
                        title: payload.set_title,
                        from: payload.from_label,
                        to: payload.to_label,
                      },
                    })}
                  {/if}
                </span>
              {:else}
                <strong>{payload.author_username ?? ""}</strong>
                <span>
                  {$_(n.kind === "mention" ? "notifications.mentioned_you" : "notifications.replied_to_you")}
                </span>
                <em>{payload.excerpt ?? ""}</em>
              {/if}
            </button>
          </li>
        {/each}
        {#if items.length === 0}
          <li class="empty">{$_("notifications.empty")}</li>
        {/if}
      </ul>
    </div>
  {/if}
</div>

<style>
  .bell { position: relative; }
  .trigger {
    background: none; border: none; cursor: pointer; font-size: 18px;
    color: inherit; padding: var(--sp-1);
  }
  .count {
    position: absolute; top: -2px; right: -4px;
    background: var(--accent-error); color: var(--text-on-accent);
    font-size: 10px; padding: 1px 4px; border-radius: 8px;
  }
  .panel {
    position: absolute; right: 0; top: 32px; width: 320px;
    background: var(--bg-elevated); border: 1px solid var(--border-default);
    border-radius: var(--r-md); box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    z-index: 100;
  }
  header {
    display: flex; justify-content: space-between; align-items: center;
    padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border-default);
  }
  .link {
    background: none; border: none; color: var(--text-muted);
    font: inherit; cursor: pointer; font-size: var(--ts-sm);
  }
  ul {
    list-style: none; padding: 0; margin: 0;
    max-height: 320px; overflow-y: auto;
  }
  li { border-top: 1px solid var(--border-default); }
  li:first-child { border-top: none; }
  li.unread { background: var(--bg-hover); }
  .item {
    display: grid; gap: 2px; width: 100%; text-align: left;
    background: none; border: none; padding: var(--sp-2) var(--sp-3);
    cursor: pointer; color: inherit; font: inherit;
  }
  li.empty {
    padding: var(--sp-3); color: var(--text-muted); font-style: italic;
  }
  em { color: var(--text-muted); font-style: italic; }
</style>
