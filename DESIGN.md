# Mercator visual system

Mercator is a quiet instrument panel for one owner checking real project and
sales data. The first view leads with the two projects and the state of their
sources. It favors legible measures, explicit dates and restrained signals over
decorative graphs.

- **Surface:** deep blue green `#101b20`; panels `#17262b`; separators
  `#375057`.
- **Signals:** mint `#72d2b3` for a healthy connection or prepared listing,
  amber `#efbd72` for missing access, muted red `#ee8e80` for a failed read.
  Color is accompanied by words.
- **Type:** Georgia for the name, headings and large readings; a clear sans
  face for controls and explanations. Monospace is limited to Worker IDs.
- **Layout:** two project instruments in a shared frame on wide screens,
  stacked on narrow screens. Sales and catalog use tables because the owner
  needs exact values and names. The monthly bars compare revenue only within
  the same currency.
- **Interaction:** refresh is an explicit control, with a six hour background
  cadence while the local server runs. The catalog search narrows a bounded
  table. CSV column matching appears only after a file is chosen.
- **States:** a missing key yields a visible pending state; a failed read
  yields an error; no stale number is shown as current. Empty sales explain
  how to add data. Keyboard focus is visible, and motion respects reduced
  motion preferences.
