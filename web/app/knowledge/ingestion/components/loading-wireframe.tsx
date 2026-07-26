'use client'

export function LoadingWireframe() {
  return (
    <div className="space-y-4">
      <div className="rounded-[2rem] border border-border/50 bg-background/80 p-5">
        <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <div className="space-y-3 rounded-[1.5rem] border border-dashed border-border/60 bg-muted/20 p-4">
            <div className="h-4 w-32 rounded-full border border-border/50" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
          </div>
          <div className="space-y-4 rounded-[1.6rem] border border-dashed border-border/60 bg-background/90 p-4">
            <div className="h-12 rounded-[1rem] border border-border/50" />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, cardIndex) => cardIndex).map((cardIndex) => (
                <div
                  key={`ingestion-placeholder-card-${cardIndex}`}
                  className="h-24 rounded-[1.25rem] border border-dashed border-border/60 bg-muted/20"
                />
              ))}
            </div>
            <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <div className="h-[18rem] rounded-[1.25rem] border border-dashed border-border/60 bg-muted/15" />
              <div className="h-[18rem] rounded-[1.25rem] border border-dashed border-border/60 bg-muted/15" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
