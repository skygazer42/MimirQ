import { create } from 'zustand'

type CommandMenuState = {
  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
}

export const useCommandMenuState = create<CommandMenuState>()((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () =>
    set((state) => ({
      open: !state.open,
    })),
}))
