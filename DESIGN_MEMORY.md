# Design Memory

## Brand Tone

- Calm, precise, trustworthy and technical.
- Keep the light Ocean identity; dark mode must feel like the same product.
- Avoid generic AI dashboards, decorative metrics, large nested cards, dense gradients and prototype-only telemetry.

## Layout & Spacing

- Use the real `AppFrame` and Navbar when evaluating product pages.
- Default page gutter: 12px; maximum workbench width: 1680px.
- Prefer continuous work surfaces, aligned columns and hairline separators for operational pages.
- Let content determine height. Do not add fixed minimum height merely to fill a screenshot.
- Use a 4px spacing base and keep related controls close.

## Typography

- Page title: existing 19px/24px MimirQ baseline with `PageTitleIcon`.
- Supporting page copy: 12px/20px.
- Primary content: 13–14px; metadata: 10–11px.
- Monospace is for IDs and tabular data, not decorative labels.

## Color & Depth

- All colors must use existing semantic tokens.
- Structural hierarchy uses subtle surface shifts and low-opacity borders.
- Rounded corners and shadows are for controls, dropdowns and primary actions—not page sections.
- Color communicates selected, ready, warning, failure or focus state; it is not decoration.

## Interaction Patterns

- Primary action copy should describe the selected endpoint: register, parse, or index.
- Empty states tell the user the next action; never summarize “0 items” as if it were a confirmation.
- Advanced options use progressive disclosure.
- Monitoring remains a separate existing workflow; do not duplicate it inside the composer.
- Before replacing an established page, verify the proposed UI inside the real product shell.

## Accessibility Rules

- Prefer native labels, radios, details/summary and semantic buttons.
- Every control requires hover, focus, disabled and loading states.
- Never rely on color alone for operational status.

## Repository Conventions

- Reuse shared Button, Select, Input, Tabs, PageTitleIcon and theme tokens.
- Preserve existing API/query logic during visual refactors.
- Add source-level layout contracts for large JSX restructuring.
