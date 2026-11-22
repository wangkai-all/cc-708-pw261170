<script>
  // Expandable view of the actually received range segments for one
  // multi-valued attribute, with coverage and fault diagnosis. The receiver
  // only marks the attribute complete when every segment stitches cleanly.
  let { report } = $props();

  const kindClass = {
    gap: 'cycle',
    overlap: 'cycle',
    stall: 'cycle',
    'invalid-tag': 'cycle',
    'empty-nonterminal': 'cycle',
  };
</script>

<details class="range-inspector">
  <summary class="row">
    <span class="mono">{report.attribute}</span>
    {#if report.complete}
      <span class="badge resolved">complete · {report.coverage.total_values} values</span>
    {:else}
      <span class="badge cycle">incomplete</span>
    {/if}
    <span class="spacer"></span>
    <span class="muted small">{report.coverage.segments ?? 0} segment(s)</span>
  </summary>

  <div style="margin-top:0.6rem" class="grid">
    <div class="row small">
      <span>covered indices:</span>
      <span class="mono">
        {report.coverage.first_index ?? '–'} … {report.coverage.last_index ?? '–'}
      </span>
      {#if report.coverage.missing_indices && report.coverage.missing_indices.length}
        <span class="bad-text">
          missing: [{report.coverage.missing_indices.join(', ')}]
        </span>
      {:else}
        <span class="ok-text">no missing indices</span>
      {/if}
    </div>

    <table>
      <thead>
        <tr>
          <th>#</th><th>request tag</th><th>response tag</th>
          <th>low</th><th>high</th><th>count</th><th>next low</th>
        </tr>
      </thead>
      <tbody>
        {#each report.segments as seg, i (i)}
          <tr>
            <td>{i}</td>
            <td class="mono small">{seg.request_tag}</td>
            <td class="mono small">{seg.response_tag}</td>
            <td>{seg.low}</td>
            <td>{seg.high === null ? '*' : seg.high}</td>
            <td>{seg.count}</td>
            <td>{seg.expected_next_low}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    {#if report.faults && report.faults.length}
      <div class="grid" style="gap:0.3rem">
        {#each report.faults as fault, i (i)}
          <div class="error small">
            <span class="badge {kindClass[fault.kind] || 'cycle'}">{fault.kind}</span>
            at segment {fault.segment_index}: {fault.detail}
          </div>
        {/each}
      </div>
    {/if}
    <p class="muted small" style="margin:0">
      A segment whose response high is <code>*</code> promises more data; the
      next request begins at <code>low + count</code>. A concrete high bound
      terminates the range conversation.
    </p>
  </div>
</details>

<style>
  .range-inspector { margin-top: 0.4rem; }
</style>
