export function ConditionBadge({ condition }: { condition: string }) {
  const label = condition.replace(/_/g, ' ');
  return <span className={`badge hr-badge-${condition}`}>{label}</span>;
}
