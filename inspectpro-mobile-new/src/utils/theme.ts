export const colors = {
  primary:    '#1e3a8a',
  primaryMid: '#2563eb',
  primaryLight:'#dbeafe',
  accent:     '#6366f1',
  success:    '#16a34a',
  successLight:'#dcfce7',
  warning:    '#d97706',
  warningLight:'#fef3c7',
  danger:     '#dc2626',
  dangerLight:'#fee2e2',
  surface:    '#ffffff',
  background: '#f8fafc',
  border:     '#e2e8f0',
  borderDark: '#cbd5e1',
  text:       '#1e293b',
  textMid:    '#475569',
  textLight:  '#94a3b8',
  muted:      '#f1f5f9',
}

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  xl: 20,
}

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
}

export const font = {
  xs:   11,
  sm:   13,
  md:   15,
  lg:   17,
  xl:   20,
  xxl:  24,
  xxxl: 30,
}

export const STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  created:    { bg: '#f1f5f9', text: '#475569', label: 'Created' },
  assigned:   { bg: '#dbeafe', text: '#1e40af', label: 'Assigned' },
  active:     { bg: '#fef3c7', text: '#92400e', label: 'Active' },
  processing: { bg: '#ede9fe', text: '#5b21b6', label: 'Processing' },
  review:     { bg: '#fce7f3', text: '#9d174d', label: 'Review' },
  complete:   { bg: '#dcfce7', text: '#14532d', label: 'Complete' },
}

export const TYPE_LABELS: Record<string, string> = {
  check_in:  'Check In',
  check_out: 'Check Out',
  mid_term:  'Mid Term',
}
