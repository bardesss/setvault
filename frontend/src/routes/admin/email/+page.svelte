<script lang="ts">
  import { _ } from "svelte-i18n";
  import type { PageData } from "./$types";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import StatusBlock from "#lib/components/StatusBlock.svelte";
  import {
    createSmtpConnector,
    patchConnector,
    testSend,
    type Connector,
    type SmtpConfigWrite,
    type SmtpEncryption,
  } from "#lib/api/connectors.ts";
  import { errorMessage } from "#lib/api/errors.ts";
  import { session } from "#lib/stores/session.ts";
  import { toast } from "#lib/stores/toast.ts";

  export let data: PageData;

  let connector: Connector | null = data.connector;
  let host = "";
  let port = 587;
  let encryption: SmtpEncryption = "starttls";
  let username = "";
  let password = "";
  let fromEmail = "";
  let fromName = "SetVault";
  let replyTo = "";
  let enabled = true;
  let passwordSet = false;

  let busy = false;
  let formError: string | null = null;
  let dryRun = false;
  let testBusy = false;

  function adopt(c: Connector | null) {
    connector = c;
    if (!c) return;
    host = c.config.host;
    port = c.config.port;
    encryption = c.config.encryption;
    username = c.config.username ?? "";
    password = "";
    fromEmail = c.config.from_email;
    fromName = c.config.from_name;
    replyTo = c.config.reply_to ?? "";
    enabled = c.enabled;
    passwordSet = c.config.password_set;
  }
  adopt(connector);

  function nullIfBlank(s: string): string | null {
    const t = s.trim();
    return t === "" ? null : t;
  }

  async function save() {
    formError = null;
    busy = true;
    try {
      const config: SmtpConfigWrite = {
        host: host.trim(),
        port: Number(port),
        encryption,
        username: nullIfBlank(username),
        from_email: fromEmail.trim(),
        from_name: fromName.trim(),
        reply_to: nullIfBlank(replyTo),
      };
      // Empty keeps the stored password; only send one that was typed.
      if (password !== "") config.password = password;
      adopt(
        connector
          ? await patchConnector(connector.id, { enabled, config })
          : await createSmtpConnector("SMTP", config, enabled),
      );
      toast.success($_("admin.email.saved"));
    } catch (e) {
      formError = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function sendTest() {
    if (!connector || !$session) return;
    testBusy = true;
    try {
      const result = await testSend(connector.id, $session.email, dryRun);
      if (result.accepted) {
        toast.success(
          result.dry_run
            ? $_("admin.email.test_dry_ok")
            : $_("admin.email.test_sent", { values: { to: $session.email } }),
        );
      } else {
        toast.error($_("admin.email.test_failed", { values: { error: result.error ?? "" } }));
      }
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      testBusy = false;
    }
  }
</script>

<h2>{$_("admin.email.title")}</h2>

<p class="hint">{$_("admin.email.intro")}</p>

<AdminForm on:submit={save}>
  {#if formError}
    <p class="admin-msg is-error" role="alert" data-testid="email-error">{formError}</p>
  {/if}
  <label class="admin-field">
    <span>{$_("admin.email.host")}</span>
    <input type="text" bind:value={host} required />
  </label>
  <label class="admin-field">
    <span>{$_("admin.email.port")}</span>
    <input type="number" min="1" max="65535" bind:value={port} required />
  </label>
  <label class="admin-field">
    <span>{$_("admin.email.security")}</span>
    <select bind:value={encryption}>
      <option value="starttls">{$_("admin.email.sec_starttls")}</option>
      <option value="ssl">{$_("admin.email.sec_ssl")}</option>
      <option value="none">{$_("admin.email.sec_none")}</option>
    </select>
  </label>
  <label class="admin-field">
    <span>{$_("admin.email.username")}</span>
    <input type="text" autocomplete="off" bind:value={username} />
  </label>
  <label class="admin-field">
    <span>{$_("admin.email.password")}</span>
    <input
      type="password"
      autocomplete="new-password"
      placeholder={passwordSet ? $_("admin.email.password_keep") : ""}
      bind:value={password}
    />
  </label>
  <small class="hint" data-testid="password-state">
    {passwordSet ? $_("admin.email.password_set") : $_("admin.email.password_not_set")}
  </small>
  <label class="admin-field">
    <span>{$_("admin.email.from_email")}</span>
    <input type="email" bind:value={fromEmail} required />
  </label>
  <label class="admin-field">
    <span>{$_("admin.email.from_name")}</span>
    <input type="text" bind:value={fromName} required />
  </label>
  <label class="admin-field">
    <span>{$_("admin.email.reply_to")}</span>
    <input type="email" bind:value={replyTo} />
  </label>
  <label class="admin-field inline">
    <input type="checkbox" bind:checked={enabled} />
    <span>{$_("admin.email.enabled")}</span>
  </label>
  <svelte:fragment slot="actions">
    <button type="submit" class="btn btn-primary" disabled={busy}>
      {$_("admin.email.save")}
    </button>
  </svelte:fragment>
</AdminForm>

<StatusBlock title={$_("admin.email.test_title")}>
  {#if connector}
    <p class="hint">{$_("admin.email.test_hint", { values: { to: $session?.email ?? "" } })}</p>
    <label class="admin-field inline">
      <input type="checkbox" bind:checked={dryRun} />
      <span>{$_("admin.email.dry_run")}</span>
    </label>
    <div>
      <button type="button" class="btn btn-sm" disabled={testBusy} on:click={sendTest}>
        {$_("admin.email.send_test")}
      </button>
    </div>
  {:else}
    <p class="hint">{$_("admin.email.test_needs_save")}</p>
  {/if}
</StatusBlock>

<style>
  .hint { color: var(--text-faint); margin: 0; font-size: var(--ts-sm); }
</style>
