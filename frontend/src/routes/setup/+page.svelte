<script lang="ts">
  import { goto, refreshAll } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import { setupFirstAdmin } from "#lib/api/auth.ts";
  import { ApiError } from "#lib/api/client.ts";

  let email = "";
  let displayName = "";
  let password = "";
  let confirm = "";
  let error: string | null = null;
  let busy = false;

  async function submit() {
    error = null;
    if (password.length < 12) { error = $_("setup.password_too_short"); return; }
    if (password !== confirm) { error = $_("setup.password_mismatch"); return; }
    busy = true;
    try {
      await setupFirstAdmin(email.trim(), password, displayName || undefined);
      await refreshAll();
      await goto("/");
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("setup.error_generic");
    } finally { busy = false; }
  }
</script>

<svelte:head><title>{$_("setup.heading")} — SetVault</title></svelte:head>

<section class="auth-shell">
  <form class="auth-card" on:submit|preventDefault={submit}>
    <div class="auth-brand">
      <span class="brand-dot"></span>
      <span class="brand-name">SETVAULT</span>
    </div>

    <h1>{$_("setup.heading")}</h1>
    <p class="auth-caption">// {$_("setup.caption")}</p>

    <label>
      <span>{$_("setup.email")}</span>
      <input type="email" bind:value={email} required autocomplete="email" />
    </label>

    <label>
      <span>{$_("setup.display_name")}</span>
      <input type="text" bind:value={displayName} autocomplete="name" />
    </label>

    <label>
      <span>{$_("setup.password")}</span>
      <input type="password" bind:value={password} required minlength="12" autocomplete="new-password" />
    </label>

    <label>
      <span>{$_("setup.confirm_password")}</span>
      <input type="password" bind:value={confirm} required autocomplete="new-password" />
    </label>

    {#if error}<p class="auth-error" role="alert">{error}</p>{/if}

    <button class="btn btn-primary" type="submit" disabled={busy}>
      {busy ? $_("setup.submitting") : $_("setup.submit")}
    </button>
  </form>
</section>
