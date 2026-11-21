import { Braces, Database, FileMarkdown, FilePdf, Globe, ShieldCheck } from '@/components/icons'
import type { GovernanceProfileSummary } from '@/types'
import { profileIdentity } from './profile-presentation'
import styles from './profiles.module.css'

const PROFILE_MARKS = {
  pdf: { Icon: FilePdf, ink: undefined },
  web: { Icon: Globe, ink: 'icon-ink-process' },
  privacy: { Icon: ShieldCheck, ink: 'icon-ink-governance' },
  code: { Icon: Braces, ink: 'icon-ink-analysis' },
  data: { Icon: Database, ink: 'icon-ink-source' },
  text: { Icon: FileMarkdown, ink: undefined },
}

export function ProfileMark({ profile }: Readonly<{ profile: GovernanceProfileSummary }>) {
  const { kind } = profileIdentity(profile)
  const { Icon, ink } = PROFILE_MARKS[kind]
  return (
    <span className={styles.profileMark} data-kind={kind}>
      <Icon appearance="color" className={ink} aria-hidden="true" />
    </span>
  )
}
