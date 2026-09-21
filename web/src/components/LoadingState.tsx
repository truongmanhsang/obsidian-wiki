export function LoadingState({ label = 'Loading memory…' }: { label?: string }) {
  return <div className="loading-state" role="status"><span className="loading-dots"><i /><i /><i /></span>{label}</div>
}
