export const LoadingState=()=> <div className="state" role="status">正在加载…</div>
export const EmptyState=({message='暂无内容'}:{message?:string})=> <div className="state">{message}</div>
export const ErrorState=({message}:{message:string})=> <div className="state error" role="alert">{message}</div>