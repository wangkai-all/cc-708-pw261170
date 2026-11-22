// Thin API client for the reception console. Every call goes to the same
// origin; the collection guard lives server-side and only knows the demo DIT.

async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      // non-JSON error body: keep the status text
    }
    const error = new Error(detail);
    error.status = resp.status;
    throw error;
  }
  return resp;
}

export const api = {
  async config() {
    return request('/api/config').then((r) => r.json());
  },

  async search(body) {
    return request('/api/search', {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((r) => r.json());
  },

  async entry(dn) {
    return request(`/api/entries/lookup?dn=${encodeURIComponent(dn)}`).then(
      (r) => r.json(),
    );
  },

  async resolveAlias(dn) {
    return request(
      `/api/aliases/resolve?dn=${encodeURIComponent(dn)}`,
    ).then((r) => r.json());
  },

  async parseDn(dn) {
    return request(`/api/dn/parse?dn=${encodeURIComponent(dn)}`).then((r) =>
      r.json(),
    );
  },

  downloadSearch(body, format) {
    // Navigate-style download via a form POST so the browser handles the
    // attachment response with the server-provided filename.
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/api/search';
    const payload = { ...body, format };
    const field = document.createElement('input');
    field.name = 'payload';
    field.value = JSON.stringify(payload);
    form.appendChild(field);
    // The endpoint expects JSON, so use fetch + blob instead of a form post.
    return request('/api/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    }).then(async (resp) => {
      const blob = await resp.blob();
      const disposition = resp.headers.get('Content-Disposition') || '';
      const match = /filename="([^"]+)"/.exec(disposition);
      const filename = match
        ? match[1]
        : `ldap-search.${format === 'ldif' ? 'ldif' : 'json'}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
  },

  binaryUrl(dn, attribute, index = 0) {
    const params = new URLSearchParams({ dn, attribute, index: String(index) });
    return `/api/attributes/binary?${params.toString()}`;
  },
};
