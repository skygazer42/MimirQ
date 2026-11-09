import { Braces, Database, FileMarkdown, FilePdf, Globe, ShieldCheck } from '@/components/icons'
import type { GovernanceProfileSummary } from '@/types'
import { profileIdentity } from './profile-presentation'
import styles from './profiles.module.css'

export function ProfileMark({ profile }: Readonly<{ profile: GovernanceProfileSummary }>) {
  const { kind } = profileIdentity(profile)
  const Icon = { pdf: FilePdf, web: Globe, privacy: ShieldCheck, code: Braces, data: Database, text: FileMarkdown }[kind] || FileMarkdown
  const ink = { web: 'icon-ink-process', privacy: 'icon-ink-governance', code: 'icon-ink-analysis', data: 'icon-ink-source' }[kind]
  return <span className={styles.profileMark} data-kind={kind}><Icon appearance="color" className={ink} aria-hidden="true" /></span>
}
