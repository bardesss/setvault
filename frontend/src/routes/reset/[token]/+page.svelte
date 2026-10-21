<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { api, ApiError } from "#lib/api/client.ts";
  let password = "", error: string | null = null;

  async function submit() {
    error = null;
    try {
      await api(`/api/password-reset/${page.params.token}/redeem`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      await goto("/login");
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "unknown error";
    }
  }
</script>

<svelte:head><title>Reset password — SetVault</title></svelte:head>

<section class="auth-shell">
  <form class="auth-card" on:submit|preventDefault={submit}>
    <div class="auth-brand">
      <span class="brand-dot"></span>
      <span class="brand-name">SETVAULT</span>
    </div>

    <h1>Reset password</h1>
    <p class="auth-caption">// set a new password</p>

    <label>
      <span>New password</span>
      <input type="password" bind:value={password} required minlength="12" />
    </label>

    {#if error}<p class="auth-error" role="alert">{error}</p>{/if}

    <button class="btn btn-primary" type="submit">Reset password</button>
  </form>
</section>
