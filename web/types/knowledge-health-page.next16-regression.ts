import KnowledgeDocumentHealthPage from '@/app/knowledge/[id]/health/page'

type Props = Parameters<typeof KnowledgeDocumentHealthPage>[0]

type Assert<T extends true> = T

type IsPromise<T> = T extends Promise<unknown> ? true : false
type ResolvedHasId<T> = Awaited<T> extends { id: string } ? true : false

type _ParamsArePromise = Assert<IsPromise<Props['params']>>
type _ResolvedParamsContainId = Assert<ResolvedHasId<Props['params']>>
