<script>
  import AttributeTable from './AttributeTable.svelte';
  import RelationshipPanel from './RelationshipPanel.svelte';

  let { entry, onNavigate, onClose } = $props();

  let tab = $state('attributes');
</script>

<div class="panel detail">
  <div class="row">
    <div>
      <h2 style="margin-bottom:0.2rem">
        <span class="badge {entry.kind}">{entry.kind}</span>
        Entry detail
      </h2>
      <div class="mono small" style="word-break:break-all">{entry.dn}</div>
    </div>
    <span class="spacer"></span>
    <button onclick={onClose}>Close</button>
  </div>

  <div class="object-classes small muted">
    objectClass:
    {#each entry.object_class as oc, i (oc)}
      <span class="tag">{oc}</span>{i < entry.object_class.length - 1 ? ' ' : ''}
    {/each}
  </div>

  <div class="row tabs">
    <button class:primary={tab === 'attributes'} onclick={() => (tab = 'attributes')}>
      Attributes ({Object.keys(entry.attributes).length})
    </button>
    <button class:primary={tab === 'relationships'} onclick={() => (tab = 'relationships')}>
      Relationships ({entry.relationships.length})
    </button>
  </div>

  {#if tab === 'attributes'}
    <AttributeTable {entry} />
  {:else}
    <RelationshipPanel {entry} {onNavigate} />
  {/if}
</div>

<style>
  .detail { display: grid; gap: 0.8rem; }
  .object-classes { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
  .tabs button { font-size: 0.85rem; }
</style>
