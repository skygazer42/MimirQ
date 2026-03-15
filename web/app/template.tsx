import { PageTransition } from "@/components/page-transition"

export default function Template({ children }: Readonly<{ children: React.ReactNode }>) {
  return <PageTransition>{children}</PageTransition>
}
