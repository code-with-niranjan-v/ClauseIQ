const LABELS = {
  COVERED: 'Covered',
  PARTIALLY_COVERED: 'Partially covered',
  NOT_COVERED: 'Not covered',
  CONFLICTING: 'Conflicting',
  UNVERIFIED: 'Unverified',
  PENDING_REVIEW: 'Pending review',
  APPROVED: 'Approved',
  APPROVED_WITH_CHANGES: 'Approved with changes',
  REJECTED: 'Rejected',
  POLICY_GAP: 'Policy gap',
  PARTIAL_POLICY_GAP: 'Partial policy gap',
  CONTROL_DESIGN_GAP: 'Control gap',
  OWNERSHIP_GAP: 'Ownership gap',
  IMPLEMENTATION_UNVERIFIED: 'Implementation unverified',
  POLICY_CONFLICT: 'Policy conflict',
  NEVER_RUN: 'Never run',
  RUNNING: 'Running',
  SUCCESS: 'Success',
  PARTIAL: 'Partial',
  FAILED: 'Failed',
  PROCESSING: 'Processing',
  WAITING_TO_PUBLISH: 'Waiting to publish',
  QUEUED: 'Queued for processing',
  DEAD_LETTERED: 'Failed after retries',
  PAUSING: 'Pausing',
  PAUSED: 'Paused',
  STARTING: 'Starting',
  DEGRADED: 'Reconnecting',
  STOPPED: 'Stopped',
  COMPLETED: 'Completed',
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
}

export const TONES = {
  COVERED: 'good', SUCCESS: 'good', COMPLETED: 'good', APPROVED: 'good', APPROVED_WITH_CHANGES: 'good', LOW: 'good',
  PARTIALLY_COVERED: 'warn', PARTIAL: 'warn', PENDING_REVIEW: 'warn', PROCESSING: 'warn', RUNNING: 'warn',
  UNVERIFIED: 'warn', MEDIUM: 'warn',
  NOT_COVERED: 'bad', CONFLICTING: 'bad', FAILED: 'bad', REJECTED: 'bad', HIGH: 'bad',
  QUEUED: 'warn', WAITING_TO_PUBLISH: 'warn', PAUSING: 'warn', PAUSED: 'warn',
  STARTING: 'warn', DEGRADED: 'warn', STOPPED: 'bad', DEAD_LETTERED: 'bad',
}

export function label(value) {
  return LABELS[value] ?? value ?? 'Not assessed'
}
