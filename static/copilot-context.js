(() => {
  const providers = new Map();
  window.mercatorCopilot = {
    register(name, provider) { providers.set(name, provider); },
    changed(fields, baseline) {
      return Object.fromEntries(Object.entries(fields).filter(([key, value]) =>
        JSON.stringify(value) !== JSON.stringify(baseline?.[key])));
    },
  };
  window.hoardCopilot = {
    async context(base) {
      const page = location.pathname + location.hash;
      let current;
      for (const provider of providers.values()) {
        current = await provider.context?.();
        if (current) break;
      }
      return { active_objects: [], ...(current || {}),
        view: { ...(base.view || {}), page, ...(current?.view || {}) } };
    },
    onTurnEnd() {
      for (const provider of providers.values()) provider.refresh?.();
    },
  };
})();
