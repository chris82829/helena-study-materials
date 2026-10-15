export function standaloneArm(path = globalThis.window?.location?.pathname || '') {
  return /^\/test\/(a|b|c)(?:\/datenschutz)?\/?$/.exec(path)?.[1]?.toUpperCase() || null;
}
export function consentPurpose(host = globalThis.window) {
  const arm = standaloneArm(host?.location?.pathname);
  return arm ? `test_${arm.toLowerCase()}` : 'study';
}

export function leavesTestContext(nextPage, pathname) {
  return nextPage === 'about' && !!standaloneArm(pathname);
}
