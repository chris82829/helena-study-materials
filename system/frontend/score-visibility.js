// Display threshold only: changing visibility never changes scores or the saved pool.
export const MIN_MATCH_SCORE = 70;

export function scoreVisibility(jobs, showLowScores = false) {
  const matching = jobs.filter(job => Number.isInteger(job.match?.score) && job.match.score >= MIN_MATCH_SCORE && job.match.score <= 100);
  return {
    visibleJobs: showLowScores ? [...jobs] : matching,
    lowCount: jobs.length - matching.length,
    matchingCount: matching.length,
  };
}

export function resultVisibilityKey(session) {
  return session ? JSON.stringify([session.session_id, session.advisor, session.jobs]) : null;
}
