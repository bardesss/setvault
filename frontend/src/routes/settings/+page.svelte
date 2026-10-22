<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import { copyText } from "#lib/clipboard.ts";
  import OfflineAudioCache from "#lib/components/OfflineAudioCache.svelte";
  import TabStrip from "#lib/components/TabStrip.svelte";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import StatusBlock from "#lib/components/StatusBlock.svelte";
  import {
    createRssToken,
    listMyRssTokens,
    revokeRssToken,
    type RssToken,
    type RssTokenWithPlaintext,
  } from "#lib/api/feeds.ts";
  import { session } from "#lib/stores/session.ts";
  import { _ } from "svelte-i18n";

  let active = "profile";
  $: tabs = [
    { id: "profile", label: $_("settings.tabs.profile") },
    { id: "security", label: $_("settings.tabs.security") },
    { id: "feeds", label: $_("settings.tabs.feeds") },
    { id: "offline", label: $_("settings.tabs.offline") },
    { id: "notifications", label: $_("settings.tabs.notifications") },
  ];

  let currentPassword = "";
  let newPassword = "";
  let error: string | null = null;
  let success: string | null = null;
  let busy = false;

  let rssTokens: RssToken[] = [];
  let rssTokensLoaded = false;
  let rssBusy = false;
  let rssNewName = "";
  let rssJustMinted: RssTokenWithPlaintext | null = null;
  let rssError: string | null = null;

  async function loadRssTokens() {
    try {
      rssTokens = await listMyRssTokens();
    } finally {
      rssTokensLoaded = true;
    }
  }

  async function mintRssToken() {
    rssError = null;
    rssBusy = true;
    try {
      const minted = await createRssToken(rssNewName.trim() || "RSS");
      const abs = (u: string) => (u.startsWith("/") ? `${location.origin}${u}` : u);
      rssJustMinted = {
        ...minted,
        favorites_url: abs(minted.favorites_url),
        recent_url: abs(minted.recent_url),
        everything_url: abs(minted.everything_url),
      };
      copyState = null;
      rssNewName = "";
      await loadRssTokens();
    } catch (e) {
      rssError = e instanceof ApiError ? e.detail : "failed";
    } finally {
      rssBusy = false;
    }
  }

  async function doRevoke(id: string) {
    rssError = null;
    try {
      await revokeRssToken(id);
      rssTokens = rssTokens.filter((t) => t.id !== id);
    } catch (e) {
      rssError = e instanceof ApiError ? e.detail : "failed";
    }
  }

  let copyState: "copied" | "failed" | null = null;

  async function copyToClipboard(text: string) {
    copyState = (await copyText(text)) ? "copied" : "failed";
  }

  type Kind = "account_security" | "mention" | "comment_reply" | "set_upgraded" | "maintenance";
  type Channel = "in_app" | "email" | "both" | "off";

  interface Pref {
    kind: string;
    channel: Channel;
    connector_id: string | null;
  }

  const KINDS: Kind[] = ["account_security", "mention", "comment_reply", "set_upgraded"];
  // Library maintenance summaries (e.g. the quality backfill) go to admins
  // only, and only in-app.
  $: kinds = $session?.role === "admin" ? [...KINDS, "maintenance" as Kind] : KINDS;
  const IN_APP_ONLY: Kind[] = ["set_upgraded", "maintenance"];

  let prefs: Record<string, Channel> = {};
  let prefsLoaded = false;

  async function loadPrefs() {
    try {
      const r = await api<{ items: Pref[] }>("/api/me/notification-preferences");
      for (const p of r.items) prefs[p.kind] = p.channel;
    } finally {
      prefsLoaded = true;
    }
  }

  async function setPref(kind: Kind, channel: Channel) {
    prefs[kind] = channel;
    prefs = prefs;
    try {
      await api(`/api/me/notification-preferences/${kind}`, {
        method: "PUT",
        body: JSON.stringify({ channel }),
      });
    } catch {
      /* surface as a separate concern; minimal UI for now */
    }
  }

  function onPrefChange(kind: Kind, ev: Event) {
    const target = ev.currentTarget as HTMLSelectElement;
    void setPref(kind, target.value as Channel);
  }

  onMount(() => {
    void loadPrefs();
    void loadRssTokens();
  });

  async function submit() {
    error = null;
    success = null;
    busy = true;
    try {
      await api("/api/me/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      success = $_("settings.password_updated");
      currentPassword = "";
      newPassword = "";
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("settings.failed");
    } finally {
      busy = false;
    }
  }
</script>

<section class="settings">
  <h1>{$_("settings.heading")}</h1>

  <TabStrip {tabs} bind:active />

  {#if active === "profile"}
    {#if $session}
      <StatusBlock
        title={$_("settings.profile")}
        rows={[
          { label: $_("settings.display_name"), value: $session.display_name },
          { label: $_("settings.username"), value: $session.username },
          { label: $_("settings.email"), value: $session.email },
          { label: $_("settings.role"), value: $session.role },
        ]}
      />
    {/if}
  {:else if active === "security"}
    <AdminForm title={$_("settings.change_password")} on:submit={submit}>
      <label class="admin-field">
        <span>{$_("settings.current_password")}</span>
        <input
          type="password"
          bind:value={currentPassword}
          required
          autocomplete="current-password"
        />
      </label>
      <label class="admin-field">
        <span>{$_("settings.new_password")}</span>
        <input
          type="password"
          bind:value={newPassword}
          required
          minlength="12"
          autocomplete="new-password"
        />
      </label>
      {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}
      {#if success}<p class="admin-msg is-success" role="status">{success}</p>{/if}
      <svelte:fragment slot="actions">
        <button type="submit" class="btn btn-primary" disabled={busy}>
          {busy ? $_("settings.saving") : $_("settings.change_password")}
        </button>
      </svelte:fragment>
    </AdminForm>
  {:else if active === "feeds"}
    <div class="feeds">
      <p class="muted">{$_("feeds.description")}</p>

      {#if rssJustMinted}
        {@const minted = rssJustMinted}
        <aside class="just-minted" role="status">
          <p><strong>{$_("feeds.shown_once")}</strong></p>
          <ul>
            <li>
              <span>{$_("feeds.favorites")}</span>
              <code>{minted.favorites_url}</code>
              <button type="button" class="btn btn-sm" on:click={() => copyToClipboard(minted.favorites_url)}>
                {$_("feeds.copy")}
              </button>
            </li>
            <li>
              <span>{$_("feeds.recent")}</span>
              <code>{minted.recent_url}</code>
              <button type="button" class="btn btn-sm" on:click={() => copyToClipboard(minted.recent_url)}>
                {$_("feeds.copy")}
              </button>
            </li>
            <li>
              <span>{$_("feeds.everything")}</span>
              <code>{minted.everything_url}</code>
              <button type="button" class="btn btn-sm" on:click={() => copyToClipboard(minted.everything_url)}>
                {$_("feeds.copy")}
              </button>
            </li>
          </ul>
          {#if copyState}
            <p class="muted" role="status" data-test="copy-state">
              {copyState === "copied" ? $_("feeds.copied") : $_("feeds.copy_failed")}
            </p>
          {/if}
          <button type="button" class="btn btn-sm" on:click={() => (rssJustMinted = null)}>OK</button>
        </aside>
      {/if}

      <AdminForm on:submit={mintRssToken}>
        <label class="admin-field">
          <span>{$_("feeds.name_label")}</span>
          <input type="text" bind:value={rssNewName} disabled={rssBusy} placeholder="Podcast app" />
        </label>
        {#if rssError}<p class="admin-msg is-error">{rssError}</p>{/if}
        <svelte:fragment slot="actions">
          <button type="submit" class="btn btn-primary" disabled={rssBusy}>
            {$_("feeds.create")}
          </button>
        </svelte:fragment>
      </AdminForm>

      {#if rssTokensLoaded && rssTokens.length > 0}
        <ul class="token-list">
          {#each rssTokens as t (t.id)}
            <li>
              <strong>{t.name}</strong>
              <span class="muted">— {t.last_used_at ? `used ${t.last_used_at.slice(0, 10)}` : "unused"}</span>
              <button type="button" class="btn btn-sm" on:click={() => doRevoke(t.id)}>{$_("feeds.revoke")}</button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {:else if active === "offline"}
    <OfflineAudioCache />
  {:else if active === "notifications"}
    <section class="status-block prefs">
      {#if !prefsLoaded}
        <p class="muted">{$_("settings.loading")}</p>
      {:else}
        <dl>
          {#each kinds as kind (kind)}
            <dt>{$_(`settings.notification_kinds.${kind}`)}</dt>
            <dd>
              <select
                value={prefs[kind] ?? (IN_APP_ONLY.includes(kind) ? "in_app" : "both")}
                on:change={(e) => onPrefChange(kind, e)}
                aria-label={$_(`settings.notification_kinds.${kind}`)}
              >
                <option value="in_app">{$_("settings.channel.in_app")}</option>
                {#if kind !== "maintenance"}
                  <option value="email">{$_("settings.channel.email")}</option>
                  <option value="both">{$_("settings.channel.both")}</option>
                {/if}
                <option value="off">{$_("settings.channel.off")}</option>
              </select>
            </dd>
          {/each}
        </dl>
      {/if}
    </section>
  {/if}
</section>

<style>
  .settings { padding: var(--sp-6); display: grid; gap: var(--sp-4); max-width: 560px; }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }

  .feeds { display: grid; gap: var(--sp-3); }
  .feeds .token-list { list-style: none; padding: 0; margin: 0;
                        display: grid; gap: var(--sp-1); }
  .feeds .token-list li { display: flex; gap: var(--sp-2);
                          align-items: baseline; flex-wrap: wrap; }
  .feeds .just-minted {
    padding: var(--sp-2); background: var(--bg-base);
    border: 1px dashed var(--accent); border-radius: var(--r-sm);
    display: grid; gap: var(--sp-2);
  }
  .feeds .just-minted ul { list-style: none; padding: 0; margin: 0;
                            display: grid; gap: var(--sp-1); }
  .feeds .just-minted li { display: grid;
                            grid-template-columns: max-content 1fr max-content;
                            gap: var(--sp-2); align-items: center; }
  .feeds .just-minted code {
    font-family: var(--font-mono); font-size: var(--ts-xs);
    overflow-wrap: anywhere;
  }

  .prefs dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: var(--sp-2) var(--sp-3);
    margin: 0;
    align-items: center;
  }
  .prefs dt { color: var(--text-faint); }
  .prefs dd { margin: 0; }
  .prefs select {
    padding: var(--sp-1) var(--sp-2);
    background: var(--bg-base);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    color: inherit;
    font: inherit;
  }

  @media (max-width: 600px) {
    .settings { padding: var(--sp-3); max-width: none; }
    input { font-size: 16px; }  /* prevents iOS auto-zoom on focus */
    .prefs dl { grid-template-columns: 1fr; gap: var(--sp-1); }
    .feeds .just-minted li {
      grid-template-columns: 1fr;
      gap: var(--sp-1);
    }
  }
</style>
