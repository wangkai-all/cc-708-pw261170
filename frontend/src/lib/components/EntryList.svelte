<script>
  // Compact result list: DN, structural kind and object types. Clicking a row
  // opens the full detail view; the DN itself is shown verbatim with escapes.
  let { entries, loading, onSelect } = $props();
</script>

<div class="panel">
  <h2>
    Results
    {#if !loading}
      <span class="muted small">({entries.length})</span>
    {/if}
  </h2>

  {#if loading}
    <p class="muted">Searching…</p>
  {:else if !entries.length}
    <p class="muted">No entries matched.</p>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th style="width:6rem">Kind</th>
            <th>Distinguished name</th>
            <th>Object type(s)</th>
          </tr>
        </thead>
        <tbody>
          {#each entries as entry (entry.dn)}
            <tr class="result-row" onclick={() => onSelect(entry.dn)} role="button" tabindex="0"
                onkeydown={(e) => e.key === 'Enter' && onSelect(entry.dn)}>
              <td><span class="badge {entry.kind}">{entry.kind}</span></td>
              <td class="mono small" style="word-break:break-all">{entry.dn}</td>
              <td class="small muted">
                {entry.object_class.slice(0, 3).join(', ')}
                {entry.object_class.length > 3 ? ' …' : ''}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .result-row { cursor: pointer; }
  .result-row:hover { background: var(--panel-2); }
  .scroll { max-height: 60vh; overflow: auto; }
</style>
