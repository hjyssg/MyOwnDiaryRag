import { useEffect } from 'react'

function isEditableTarget(target: EventTarget | null) {
  const element = target instanceof HTMLElement ? target : null
  return Boolean(
    element?.isContentEditable ||
    element?.closest('input, textarea, select, [contenteditable="true"]'),
  )
}

/** 为前进 / 后退提供方向键及常见鼠标侧键（button 3 / 4）快捷操作。 */
export function useNavigationShortcuts({
  previous,
  next,
}: {
  previous?: () => void
  next?: () => void
}) {
  useEffect(() => {
    const navigate = (direction: 'previous' | 'next', event: Event) => {
      const action = direction === 'previous' ? previous : next
      if (!action || isEditableTarget(event.target)) return
      event.preventDefault()
      action()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      if (event.key === 'ArrowLeft') navigate('previous', event)
      if (event.key === 'ArrowRight') navigate('next', event)
    }
    const onMouseDown = (event: MouseEvent) => {
      if (event.button === 3) navigate('previous', event)
      if (event.button === 4) navigate('next', event)
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('mousedown', onMouseDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('mousedown', onMouseDown)
    }
  }, [previous, next])
}
