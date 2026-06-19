export function sanitizeUserSkillIdsForProjectPayload(ids, hiddenSkillIds = []) {
  const hidden = new Set(hiddenSkillIds || []);
  return [...(ids || [])].filter(id => !hidden.has(id));
}

export function selectedCapabilitiesForPayload(capabilities, taskTypes, defaultCapabilities, hiddenSkillIds = []) {
  const out = {};
  for (const task of taskTypes || []) {
    const entry = capabilities?.[task.key] || defaultCapabilities();
    out[task.key] = {
      mcp_server_ids: [...(entry.user_mcp_server_ids || entry.mcp_server_ids || [])],
      skill_ids: sanitizeUserSkillIdsForProjectPayload(entry.user_skill_ids || [], hiddenSkillIds),
    };
  }
  return out;
}
