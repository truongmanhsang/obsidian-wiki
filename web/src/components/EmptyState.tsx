export function EmptyState({ title, message }: { title: string; message: string }) {
  return <div className="empty-panel"><div className="empty-orb">✦</div><h2>{title}</h2><p>{message}</p></div>
}
