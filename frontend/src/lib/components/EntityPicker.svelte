<script lang="ts">
  import { createEventDispatcher, onDestroy, tick } from "svelte";
  import { _ } from "svelte-i18n";
  import { lookup, type LookupKind, type LookupRow } from "#lib/api/lookup.ts";
  import { toast } from "#lib/stores/toast.ts";
  import { moveItem, nextIndex, offerCreate } from "#lib/entity-picker.ts";

  export let kind: LookupKind;
  export let multiple = false;
  export let value: LookupRow[] = [];
  export let allowCreate = false;
  export let placeholder = "";

  const dispatch = createEventDispatcher<{
    create: { name: string };
    change: LookupRow[];
  }>();

  const DEBOUNCE_MS = 200;
  const uid = `ep-${Math.random().toString(36).slice(2, 9)}`;

  let query = "";
  let results: LookupRow[] = [];
  let open = false;
  let active = -1;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let seq = 0;
  let pending = false; // a lookup is debounced or in flight for the current query
  let failed = false; // the last lookup errored
  let fieldEl: HTMLElement | undefined;

  $: selectedIds = new Set(value.map((v) => v.id));
  $: visible = results.filter((r) => !selectedIds.has(r.id));
  // Never offer "create" on stale or unknown results: that is how duplicates get made.
  $: showCreate =
    allowCreate && !pending && !failed && offerCreate(query, results, value);
  $: rowCount = visible.length + (showCreate ? 1 : 0);
  $: showInput = multiple || value.length === 0;

  function setValue(next: LookupRow[]) {
    value = next;
    dispatch("change", next);
  }

  function schedule() {
    clearTimeout(timer);
    const q = query;
    failed = false;
    if (!q.trim()) {
      seq++;
      pending = false;
      results = [];
      active = -1;
      return;
    }
    pending = true;
    active = -1;
    timer = setTimeout(() => void run(q), DEBOUNCE_MS);
  }

  async function run(q: string) {
    const mine = ++seq;
    try {
      const rows = await lookup(kind, q.trim());
      if (mine !== seq) return;
      results = rows;
      failed = false;
    } catch {
      if (mine !== seq) return;
      results = [];
      failed = true;
      toast.error($_("picker.lookup_failed"));
    }
    pending = false;
    await tick(); // let the reactive row count settle
    active = rowCount > 0 ? 0 : -1;
  }

  function onInput() {
    open = true;
    schedule();
  }

  function pick(row: LookupRow) {
    setValue(multiple ? [...value, row] : [row]);
    reset();
    if (!multiple) void focusChipRemove();
  }

  async function focusChipRemove() {
    await tick();
    fieldEl?.querySelector<HTMLElement>("[data-remove]")?.focus();
  }

  function create() {
    const name = query.trim();
    if (!name) return;
    dispatch("create", { name });
    reset();
  }

  function reset() {
    clearTimeout(timer);
    seq++;
    pending = false;
    failed = false;
    query = "";
    results = [];
    active = -1;
    open = false;
  }

  function remove(index: number) {
    setValue(value.filter((_v, i) => i !== index));
  }

  function move(index: number, delta: 1 | -1) {
    setValue(moveItem(value, index, index + delta));
  }

  function onKeydown(ev: KeyboardEvent) {
    switch (ev.key) {
      case "ArrowDown":
      case "ArrowUp":
        ev.preventDefault();
        open = true;
        active = nextIndex(active, ev.key === "ArrowDown" ? 1 : -1, rowCount);
        break;
      case "Enter":
        if (!open) return;
        ev.preventDefault();
        if (active >= 0 && active < visible.length) pick(visible[active]);
        else if (active === visible.length && showCreate) create();
        break;
      case "Backspace":
        if (query === "" && value.length > 0) remove(value.length - 1);
        break;
      case "Escape":
        if (open) {
          ev.stopPropagation();
          open = false;
          active = -1;
        }
        break;
    }
  }

  function onBlur() {
    open = false;
  }

  onDestroy(() => clearTimeout(timer));
</script>

<div class="picker">
  <div class="field" bind:this={fieldEl}>
    {#each value as item, i (item.id)}
      <span class="chip">
        <span class="chip-name">{item.name}</span>
        <slot name="chip" {item} />
        {#if multiple}
          <button
            type="button"
            class="chip-btn"
            aria-label={$_("picker.move_up")}
            disabled={i === 0}
            on:click={() => move(i, -1)}>↑</button
          >
          <button
            type="button"
            class="chip-btn"
            aria-label={$_("picker.move_down")}
            disabled={i === value.length - 1}
            on:click={() => move(i, 1)}>↓</button
          >
        {/if}
        <button
          type="button"
          class="chip-btn"
          data-remove
          aria-label={$_("picker.remove", { values: { name: item.name } })}
          on:click={() => remove(i)}>×</button
        >
      </span>
    {/each}
    {#if showInput}
      <input
        type="text"
        role="combobox"
        aria-expanded={open && rowCount > 0}
        aria-controls="{uid}-list"
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${uid}-opt-${active}` : undefined}
        autocomplete="off"
        {placeholder}
        bind:value={query}
        on:input={onInput}
        on:keydown={onKeydown}
        on:focus={() => {
          if (query.trim()) open = true;
        }}
        on:blur={onBlur}
      />
    {/if}
  </div>
  {#if open && rowCount > 0}
    <ul class="list" id="{uid}-list" role="listbox">
      {#each visible as row, i (row.id)}
        <li
          id="{uid}-opt-{i}"
          role="option"
          aria-selected={i === active}
          class:active={i === active}
          on:mousedown|preventDefault={() => pick(row)}
          on:mouseenter={() => (active = i)}
        >
          <span>{row.name}</span>
          {#if row.hint}<span class="hint">{row.hint}</span>{/if}
        </li>
      {/each}
      {#if showCreate}
        <li
          id="{uid}-opt-{visible.length}"
          role="option"
          aria-selected={active === visible.length}
          class="create"
          class:active={active === visible.length}
          on:mousedown|preventDefault={create}
          on:mouseenter={() => (active = visible.length)}
        >
          {$_("picker.create", { values: { name: query.trim() } })}
        </li>
      {/if}
    </ul>
  {/if}
</div>

<style>
  .picker { position: relative; }
  .field {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--sp-1);
    padding: var(--sp-1) var(--sp-2);
    background: var(--bg-input);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
  }
  .field:focus-within { border-color: var(--border-focus); }
  input {
    flex: 1;
    min-width: 8em;
    padding: var(--sp-1);
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-default);
    font: inherit;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    padding: 2px var(--sp-2);
    background: var(--accent-soft);
    color: var(--text-strong);
    border-radius: var(--r-pill);
    font-size: var(--ts-md);
  }
  .chip-btn {
    background: none;
    border: none;
    padding: 0 2px;
    color: var(--text-muted);
    cursor: pointer;
    font: inherit;
    line-height: 1;
  }
  .chip-btn:hover:not(:disabled) { color: var(--text-strong); }
  .chip-btn:disabled { opacity: 0.35; cursor: default; }
  .list {
    position: absolute;
    left: 0;
    right: 0;
    top: 100%;
    margin: 2px 0 0;
    padding: var(--sp-1) 0;
    list-style: none;
    max-height: 260px;
    overflow-y: auto;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--shadow-md);
    z-index: var(--z-overlay);
  }
  li {
    display: flex;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    cursor: pointer;
    color: var(--text-default);
  }
  li.active { background: var(--bg-hover); }
  li.create { color: var(--accent); }
  .hint { color: var(--text-muted); font-size: var(--ts-sm); }
</style>
