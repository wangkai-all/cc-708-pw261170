<script>
  // Renders any DN through the library-based parser endpoint, showing the RDN
  // chain leaf-first. Multi-valued RDNs show all AVAs; escapes are preserved
  // in the wire text and shown unescaped alongside for readability.
  import { api } from '../api';

  let { dn = $bindable('') } = $props();
  let result = $state(null);
  let error = $state('');
  let loading = $state(false);

  async function inspect() {
    if (!dn.trim()) return;
    loading = true;
    error = '';
    try {
      result = await api.parseDn(dn.trim());
    } catch (e) {
      result = null;
      error = e.message;
    } finally {
      loading = false;
    }
  }
</script>

<div class="panel grid">
  <h2>DN inspector</h2>
  <p class="muted small" style="margin-top:0">
    Parsed with ldap3's RFC 4514 state machine — never a comma split. Try
    <code>cn=Doe\, John,ou=people,dc=demo,dc=local</code> or
    <code>cn=alice+uid=alice99,ou=people,dc=demo,dc=local</code>.
  </p>
  <div class="row">
    <input bind:value={dn} placeholder="paste a distinguished name"
           onkeydown={(e) => e.key === 'Enter' && inspect()} />
    <button class="primary" onclick={inspect} disabled={loading}>Parse</button>
  </div>

  {#if error}
    <div class="error small">{error}</div>
  {/if}

  {#if result}
    <div class="grid" style="gap:0.4rem">
      <div>
        <span class="muted small">Normalized wire DN:</span>
        <div class="mono">{result.dn}</div>
      </div>
      {#if result.parent}
        <div class="small muted">parent: <span class="mono">{result.parent}</span></div>
      {/if}
      <table>
        <thead>
          <tr><th>#</th><th>RDN (leaf → root)</th><th>AVAs</th></tr>
        </thead>
        <tbody>
          {#each result.rdns as rdn, i (i)}
            <tr>
              <td>{i}</td>
              <td>
                <span class="mono">{rdn.rendered}</span>
                {#if rdn.multi_valued}
                  <span class="badge alias" style="margin-left:0.4rem">multi-valued</span>
                {/if}
              </td>
              <td>
                {#each rdn.avas as ava (ava.type + ava.value)}
                  <div class="small">
                    <span class="tag">{ava.type}</span> =
                    <span class="mono">{ava.value}</span>
                  </div>
                {/each}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
