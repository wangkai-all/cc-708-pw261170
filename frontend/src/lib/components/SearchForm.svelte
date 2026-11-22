<script>
  // Search root, scope, attribute and field selectors. The allowed bases and
  // scopes come straight from /api/config — the frontend never invents a base.
  let {
    config,
    query = $bindable(),
    loading = false,
    onSearch,
    onDownload,
  } = $props();

  let fieldRows = $state([{ attribute: 'cn', value: '', match: 'substring' }]);

  function addField() {
    fieldRows.push({ attribute: 'cn', value: '', match: 'substring' });
    sync();
  }
  function removeField(index) {
    fieldRows.splice(index, 1);
    sync();
  }
  function sync() {
    query.field_filters = fieldRows.filter((f) => f.attribute.trim());
  }
  function resetFields() {
    fieldRows = [{ attribute: 'cn', value: '', match: 'substring' }];
    query.field_filters = [];
  }
</script>

<div class="panel grid">
  <h2>Search the demo directory</h2>

  <label class="grid" style="gap:0.25rem">
    <span class="muted small">Search root (allowed collection points only)</span>
    <select bind:value={query.base_dn}>
      {#each config.allowed_search_bases as base}
        <option value={base}>{base}</option>
      {/each}
    </select>
  </label>

  <div class="row">
    <label class="grid" style="gap:0.25rem; flex:1">
      <span class="muted small">Scope</span>
      <select bind:value={query.scope}>
        {#each config.scopes as scope}
          <option value={scope.value}>{scope.label}</option>
        {/each}
      </select>
    </label>
    <label class="grid" style="gap:0.25rem; flex:1">
      <span class="muted small">Size limit</span>
      <input type="number" min="1" max="200" bind:value={query.size_limit} />
    </label>
  </div>

  <label class="grid" style="gap:0.25rem">
    <span class="muted small">
      Attributes (comma-separated, <code>*</code> for all)
    </span>
    <input
      bind:value={query.attributesText}
      placeholder="*"
      oninput={() =>
        (query.attributes = query.attributesText
          .split(',')
          .map((a) => a.trim())
          .filter(Boolean))}
    />
  </label>

  <label class="grid" style="gap:0.25rem">
    <span class="muted small">Object class filter (optional)</span>
    <input bind:value={query.object_class} placeholder="e.g. inetOrgPerson" />
  </label>

  <div class="grid" style="gap:0.4rem">
    <span class="muted small">Field filters</span>
    {#each fieldRows as row, index (index)}
      <div class="row">
        <input
          style="flex:1"
          bind:value={row.attribute}
          placeholder="attribute"
          oninput={sync}
        />
        <select style="width: 8.5rem" bind:value={row.match} onchange={sync}>
          <option value="exact">equals</option>
          <option value="substring">contains</option>
          <option value="starts">starts with</option>
          <option value="present">present</option>
        </select>
        <input
          style="flex:1"
          bind:value={row.value}
          placeholder="value"
          disabled={row.match === 'present'}
          oninput={sync}
        />
        <button onclick={() => removeField(index)} title="Remove filter">✕</button>
      </div>
    {/each}
    <div class="row">
      <button onclick={addField}>+ field</button>
      <button onclick={resetFields}>reset</button>
    </div>
  </div>

  <details>
    <summary class="small">Range fault injection (demo test hook)</summary>
    <div class="row" style="margin-top:0.5rem">
      <select
        style="flex:1"
        bind:value={query.faultKind}
        onchange={() =>
          (query.range_fault = query.faultKind
            ? { kind: query.faultKind, attribute: query.faultAttribute }
            : null)}
      >
        <option value="">no fault</option>
        {#each config.fault_kinds as kind}
          <option value={kind}>{kind}</option>
        {/each}
      </select>
      <select
        style="flex:1"
        bind:value={query.faultAttribute}
        onchange={() =>
          query.faultKind &&
          (query.range_fault = {
            kind: query.faultKind,
            attribute: query.faultAttribute,
          })}
      >
        {#each config.ranged_attributes as attr}
          <option value={attr}>{attr}</option>
        {/each}
      </select>
    </div>
    <p class="muted small" style="margin-bottom:0">
      Corrupts the second range segment so you can watch the receiver detect a
      gap, overlap or non-advancing boundary.
    </p>
  </details>

  <div class="row">
    <button class="primary" onclick={onSearch} disabled={loading}>
      {loading ? 'Searching…' : 'Search'}
    </button>
    <button onclick={() => onDownload('json')} disabled={loading}>
      Download JSON
    </button>
    <button onclick={() => onDownload('ldif')} disabled={loading}>
      Download LDIF
    </button>
  </div>
</div>
