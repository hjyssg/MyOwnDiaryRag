import type { ReactNode } from 'react'

/**
 * 独立开关控件：原生 checkbox（保留可访问名、键盘可达、可被表单读取）+ 兄弟节点自绘轨道。
 *
 * 单独抽组件的原因：筛选栏的 `.filters input` 通配样式（`min-width: 92px`、移动端 `width: 100%`）
 * 会把裸 checkbox 撑成大块空白；这里让 track 自带 34×18 尺寸，并配合
 * `.filters input:not([type='checkbox'])` 让开关完全不受筛选输入框样式影响。
 */
export function Switch({
  name,
  checked,
  onChange,
  children,
}: {
  name: string
  checked: boolean
  onChange: (checked: boolean) => void
  children: ReactNode
}) {
  return (
    <label className="switch">
      <input
        className="switch-input"
        type="checkbox"
        name={name}
        value="1"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {/* 视觉轨道放在兄弟节点上：input 是替换元素，伪元素渲染跨浏览器不一致 */}
      <span className="switch-track" aria-hidden="true" />
      <span className="switch-text">{children}</span>
    </label>
  )
}
