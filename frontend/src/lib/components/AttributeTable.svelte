<script>
  // All attributes of one entry: multi-valued values rendered as lists,
  // binary values shown as base64 with a raw download link rather than
  // forced UTF-8 text. Ranged attributes embed the segment inspector.
  import RangeInspector from './RangeInspector.svelte';
  import { api } from '../api';

  let { entry } = $props();

  const attrNames = $derived(
    Object.entries(entry.attributes)
      .map(([name, attr]) => ({ name, attr }))
      .sort((a, b) => a.name.localeCompare(b.name)),
  );
</script>

<div class="grid" style="gap:0.5rem">
  {#each attrNames as { name, attr } (name)}
    <details>
      <summary class="row">
        <span class="mono">{name}</span>
        <span class="badge {attr.syntax}">{attr.syntax}</span>
        {#if attr.multi_valued}
          <span class="badge text">multi · {attr.values.length}</span>
        {/if}
        {#if !attr.complete}
          <span class="badge cycle">partial</span>
        {/if}
        <span class="spacer"></span>
      </summary>

      <div style="margin-top:0.5rem" class="grid">
        {#each attr.values as value, index (index)}
          <div class="value-row small">
            <span class="muted mono">[{index}]</span>
            {#if value.kind === 'text'}
              <span class="mono value-text">{value.value}</span>
            {:else}
              <span class="bad-text">binary · {value.size} bytes</span>
              <a
                href={api.binaryUrl(entry.dn, name, index)}
                target="_blank"
                rel="noreferrer"
                class="small"
              >
                download raw
              </a>
              <details class="b64">
                <summary class="muted">base64</summary>
                <code class="small break">{value.base64}</code>
              </details>
              {#if value.utf8_error}
                <span class="muted small">({value.utf8_error})</span>
              {/if}
            {/if}
          </div>
        {/each}
      </div>
    </details>
  {/each}

  {#if Object.keys(entry.range_reports || {}).length > 0}
    <h3 style="margin-top:0.6rem">Range retrieval segments</h3>
    {#each Object.values(entry.range_reports) as report (report.attribute)}
      <RangeInspector {report} />
    {/each}
  {/if}
</div>

<style>
  .value-row {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
    flex-wrap: wrap;
    padding: 0.15rem 0;
  }
  .value-text {
    white-space: pre-wrap;
    word-break: break-word;
  }
  .break {
    word-break: break-all;
    white-space: pre-wrap;
  }
  .b64 {
    flex-basis: 100%;
  }
</style>
