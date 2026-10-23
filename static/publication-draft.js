/* Only editable content belongs to a new draft; identity and observations stay with the source. */
((root) => {
  function fromContent(fields) {
    const content = {};
    for (const key of ['platform', 'title', 'caption', 'hashtags', 'media_ref', 'notes']) {
      const value = fields[key] ?? '';
      content[key] = Array.isArray(value) ? value.slice() : value;
    }
    return {...content, status: 'draft'};
  }
  root.mercatorDraft = {fromContent};
})(window);
