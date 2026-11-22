<script>
  // Relationships are kept in three distinct buckets by kind. Alias entries
  // can be expanded (dereferenced) on demand; a cycle blocks expansion but the
  // entries stay. External references are displayed, never auto-followed.
  import { api } from '../api';

  let { entry, onNavigate } = $props();

  const groups = $derived(
    buildGroups(entry.relationships || []),
  );
  let resolutions = $state({}); // dn -> resolution payload
  let busy = $state('');

  function buildGroups(rels) {
    const buckets = {
      alias: [],
      referral: [],
      'external-ref': [],
      member: [],
    };
    for (const rel of rels) {
      (buckets[rel.kind] || (buckets[rel.kind] = [])).push(rel);
    }
    return Object.entries(buckets)
      .filter(([, list]) => list.length)
      .map(([kind, list]) => ({ kind, list }));
  }

  const labels = {
    alias: 'Alias targets (aliasedObjectName)',
    referral: 'Referral objects (external, not followed)',
    'external-ref': 'Cross-root DN references (external)',
    member: 'Regular membership / DN links',
  };

  async function expandAlias(rel) {
    busy = rel.target_dn;
    try {
      resolutions[rel.target_dn] = await api.resolveAlias(entry.dn);
    } catch (e) {
      resolutions[rel.target_dn] = { status: 'error', chain: [e.message] };
    } finally {
      busy = '';
    }
  }

  function statusBadge(status) {
    if (status === 'resolved') return 'resolved';
    if (status === 'cycle') return 'cycle';
    if (status === 'external') return 'external';
    return 'text';
  }
</script>

<div class="grid" style="gap:0.6rem">
  {#each groups as group (group.kind)}
    <div>
      <h3 class="small muted" style="margin:0 0 0.3rem">
        {labels[group.kind] || group.kind}
      </h3>
      <table>
        <tbody>
          {#each group.list as rel, i (rel.attribute + rel.target_dn + i)}
            <tr>
              <td style="width:9rem">
                <span class="tag">{rel.attribute}</span>
              </td>
              <td>
                <div class="row" style="gap:0.4rem">
                  <span class="badge {statusBadge(rel.status)}">{rel.status}</span>
                  {#if rel.external_url}
                    <span class="mono small external-text">{rel.external_url}</span>
                  {:else}
                    <span class="mono small">{rel.target_dn}</span>
                  {/if}
                </div>

                {#if group.kind === 'alias'}
                  <div class="row" style="margin-top:0.3rem">
                    <button
                      class="small"
                      onclick={() => expandAlias(rel)}
                      disabled={busy === rel.target_dn}
                    >
                      {busy === rel.target_dn ? 'Resolving…' : 'Expand alias'}
                    </button>
                    {#if resolutions[rel.target_dn]}
                      {@const r = resolutions[rel.target_dn]}
                      <span class="badge {statusBadge(r.status)}">{r.status}</span>
                      {#if r.resolved_dn}
                        <button class="link small mono" onclick={() => onNavigate(r.resolved_dn)}>
                          → {r.resolved_dn}
                        </button>
                      {/if}
                      {#if r.cycle_path}
                        <div class="small bad-text" style="flex-basis:100%">
                          cycle blocked:
                          {r.cycle_path.join('  →  ')}
                        </div>
                      {/if}
                      {#if r.chain && r.chain.length}
                        <div class="small muted" style="flex-basis:100%">
                          chain: {r.chain.join(' → ')}
                        </div>
                      {/if}
                    {/if}
                  </div>
                {/if}

                {#if rel.inside_root && group.kind === 'member' && rel.status === 'present'}
                  <button class="link small" onclick={() => onNavigate(rel.target_dn)}>
                    open entry
                  </button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/each}
  {#if !entry.relationships || !entry.relationships.length}
    <p class="muted small">No DN-valued relationships on this entry.</p>
  {/if}
</div>
