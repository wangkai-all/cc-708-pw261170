<script>
  import { onMount } from 'svelte';
  import { api } from './lib/api';
  import SearchForm from './lib/components/SearchForm.svelte';
  import EntryList from './lib/components/EntryList.svelte';
  import EntryDetail from './lib/components/EntryDetail.svelte';
  import DnInspector from './lib/components/DnInspector.svelte';

  let config = $state(null);
  let configError = $state('');

  let query = $state({
    base_dn: 'dc=demo,dc=local',
    scope: 'sub',
    attributesText: '*',
    attributes: ['*'],
    object_class: '',
    field_filters: [],
    size_limit: 100,
    range_fault: null,
    faultKind: '',
    faultAttribute: 'member',
  });

  let result = $state(null);
  let loading = $state(false);
  let searchError = $state('');
  let detailDn = $state('');
  let detailEntry = $state(null);
  let detailLoading = $state(false);

  onMount(async () => {
    try {
      config = await api.config();
      query.faultAttribute = config.ranged_attributes[0] || 'member';
      // Run an initial subtree search so the page is useful immediately.
      await runSearch();
    } catch (e) {
      configError = e.message;
    }
  });

  async function runSearch() {
    if (!config) return;
    loading = true;
    searchError = '';
    try {
      const body = {
        base_dn: query.base_dn,
        scope: query.scope,
        attributes: query.attributes.length ? query.attributes : ['*'],
        object_class: query.object_class || null,
        field_filters: query.field_filters,
        size_limit: Number(query.size_limit) || 100,
        range_fault: query.range_fault,
      };
      result = await api.search(body);
    } catch (e) {
      searchError = e.message;
      result = null;
    } finally {
      loading = false;
    }
  }

  async function download(format) {
    const body = {
      base_dn: query.base_dn,
      scope: query.scope,
      attributes: query.attributes.length ? query.attributes : ['*'],
      object_class: query.object_class || null,
      field_filters: query.field_filters,
      size_limit: Number(query.size_limit) || 100,
      range_fault: query.range_fault,
    };
    try {
      await api.downloadSearch(body, format);
    } catch (e) {
      searchError = e.message;
    }
  }

  async function openDetail(dn) {
    detailDn = dn;
    detailLoading = true;
    detailEntry = null;
    try {
      detailEntry = await api.entry(dn);
    } catch (e) {
      searchError = e.message;
    } finally {
      detailLoading = false;
    }
  }

  function closeDetail() {
    detailDn = '';
    detailEntry = null;
  }
</script>

<header class="app-header">
  <div>
    <h1>LDAP Reception Console</h1>
    <p class="muted small" style="margin:0">
      Read-only access to the bundled demo directory
      {#if config}<span class="mono">({config.naming_context})</span>{/if}
      · range retrieval, alias loops and referrals handled explicitly
    </p>
  </div>
</header>

{#if configError}
  <main class="layout">
    <div class="error">Backend unreachable: {configError}</div>
  </main>
{:else if !config}
  <main class="layout"><p class="muted">Loading configuration…</p></main>
{:else}
  <main class="layout">
    <section class="left grid">
      <SearchForm
        {config}
        bind:query
        {loading}
        onSearch={runSearch}
        onDownload={download}
      />
      <DnInspector />
    </section>

    <section class="right grid">
      {#if searchError}
        <div class="error">{searchError}</div>
      {/if}
      {#if result}
        <div class="panel small muted">
          filter <span class="mono">{result.filter}</span> · scope
          <span class="mono">{result.scope}</span> · {result.count} shown
          {#if result.total_matches !== result.count}
            · <span class="warn-text">{result.total_matches} matched (truncated)</span>
          {/if}
        </div>
      {/if}
      <EntryList
        entries={result ? result.entries : []}
        {loading}
        onSelect={openDetail}
      />
    </section>
  </main>

  {#if detailDn}
    <div class="overlay" onclick={closeDetail} role="presentation"></div>
    <aside class="drawer">
      {#if detailLoading}
        <div class="panel"><p class="muted">Loading {detailDn}…</p></div>
      {:else if detailEntry}
        <EntryDetail entry={detailEntry} onNavigate={openDetail} onClose={closeDetail} />
      {/if}
    </aside>
  {/if}
{/if}

<style>
  .app-header {
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  .app-header h1 { margin: 0 0 0.25rem; font-size: 1.25rem; }
  .layout {
    display: grid;
    grid-template-columns: minmax(22rem, 26rem) 1fr;
    gap: 1rem;
    padding: 1rem 1.5rem;
    align-items: start;
  }
  .left, .right { min-width: 0; }
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 10;
  }
  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(56rem, 92vw);
    background: var(--bg);
    border-left: 1px solid var(--border);
    padding: 1rem;
    overflow: auto;
    z-index: 11;
  }
  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; }
  }
</style>
