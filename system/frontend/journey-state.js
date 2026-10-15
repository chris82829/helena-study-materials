/** Return the guide step for the user's current activity. */
export function currentJourneyStep({
  hasSession = false,
  onboardingStep = 1,
  editor = null,
  activity = 'results',
  busy = false,
  operation = null,
} = {}) {
  if (!hasSession) {
    if (busy && operation?.kind === 'onboard') return 3;
    return onboardingStep === 2 ? 2 : 1;
  }
  if (editor === 'profile') return 1;
  if (editor === 'advisor') return 2;
  if (busy && ['rerank', 'refresh'].includes(operation?.kind)) return 3;
  return activity === 'chat' ? 4 : 3;
}

/** Allow the active step and earlier available destinations while idle. */
export function canVisitJourneyStep(step, {
  hasSession = false,
  activeStep = 1,
  busy = false,
  booting = false,
} = {}) {
  if (!Number.isInteger(step) || step < 1 || step > 4 ||
      !Number.isInteger(activeStep) || activeStep < 1 || activeStep > 4 ||
      step > activeStep || busy || booting) return false;
  return step < 3 || Boolean(hasSession);
}
