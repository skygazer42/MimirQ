import re

# Read file
with open('frontend/components/navbar.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the function signature
old_sig = '''export function Navbar({
  isSidebarOpen,
  setSidebarOpen,
}: {
  isSidebarOpen: boolean
  setSidebarOpen: (isOpen: boolean) => void
}) {
  const pathname = usePathname()'''

new_sig = '''export function Navbar({
  isSidebarOpen: externalIsOpen,
  setSidebarOpen: externalSetOpen,
}: {
  isSidebarOpen?: boolean
  setSidebarOpen?: (isOpen: boolean) => void
} = {}) {
  const [internalIsOpen, setInternalIsOpen] = useState(true)
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const pathname = usePathname()'''

content = content.replace(old_sig, new_sig)

# Write back
with open('frontend/components/navbar.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done!')
