'use strict';
// Pure admission decision. Only the trusted collector may supply this snapshot.
const RESOURCES = ['cpu', 'memoryGiB', 'pods', 'storageGiB'];
function signupAdmission(snapshot, registered, now = Date.now()) {
  const deny = reason => ({allowed:false, reason});
  if (!snapshot || snapshot.available !== true) return deny('capacity-unavailable');
  const age = now - Date.parse(snapshot.observedAt);
  if (!Number.isFinite(age) || age < -5000 || age >= 60000) return deny('capacity-stale');
  const c = snapshot.capacity;
  if (c?.version !== 1 || c.additionalDeploymentsComplete !== true ||
      !Number.isSafeInteger(registered) || registered < 0 || c.mainRegistered !== registered ||
      !Array.isArray(c.additionalDeployments) || !Number.isSafeInteger(c.additionalAccounts) ||
      c.additionalAccounts < 0 || c.additionalAccounts > 8 ||
      c.additionalDeployments.length !== c.additionalAccounts ||
      c.additionalDeployments.some(x => !x || x.accounts !== 1 || typeof x.label !== 'string') ||
      new Set(c.additionalDeployments.map(x => x.label)).size !== c.additionalAccounts)
    return deny('capacity-incomplete');
  const usage = c.observedUsage, usageAge = now - Date.parse(usage?.timestamp);
  if (!usage || !Number.isFinite(usageAge) || usageAge < -5000 || usageAge >= 90000 ||
      !['cpu','memoryGiB','reservedCPU','reservedMemoryGiB'].every(k => Number.isFinite(usage[k]) && usage[k] >= 0))
    return deny('usage-unavailable');
  if (!Array.isArray(c.resources) || c.resources.length !== 4 ||
      c.resources.some(x => !x || !RESOURCES.includes(x.resource) ||
        !['available','reserve','pairBudget'].every(k => Number.isFinite(x[k]) && x[k] >= 0) || x.pairBudget <= 0) ||
      new Set(c.resources.map(x => x.resource)).size !== 4)
    return deny('capacity-incomplete');
  // A new account holds storage only; compute is admitted at sign-in, first
  // come, first served. Only a lack of storage stops new registrations.
  const blocked = c.resources.filter(x => x.resource === 'storageGiB' && x.available + 1e-9 < x.reserve + x.pairBudget).map(x => x.resource);
  if (blocked.length) return {...deny('resource-pressure'), resources:blocked};
  return {allowed:true, reason:'capacity-healthy'};
}
module.exports = {signupAdmission};
