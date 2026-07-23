# BAS Graphics Source Catalog

Reviewed: July 23, 2026

## Decision

The shipped graphics library is original, code-generated SVG. External libraries are
used for workflow, coverage, and proportion research unless their license explicitly
permits redistribution in this repository.

Do not copy, trace, train from, or commit vendor artwork. Do not place restricted
downloads in Git, including private repositories.

## Niagara-Native Sources

| Source | Coverage | License / constraint | Decision |
| --- | --- | --- | --- |
| [NiagaraMods PX Exchange](https://niagaramodules.com/exchange/categories/px) | AHU, VAV, fan-powered VAV, chilled water, hot water, building templates | Commercial and noncommercial Niagara use is allowed with notice; internet and source-repository redistribution is prohibited | Evaluate only through a customer-licensed, gitignored side-load |
| [NiagaraMods Images](https://niagaramodules.com/exchange/categories/images) | Callouts, displays, arrows, tanks, thermostats, utility images | Same NiagaraMods redistribution restriction | Reference only |
| [BoostPx](https://www.niagaramarketplace.com/boostpx-flyer.html) | Modern replacement styling for standard `kitPxN4svg` | Free Niagara module; compatibility varies by Niagara release | Evaluate in a Niagara 4.10+ station |
| [Niagara `kitPxN4svg`](https://downloads.innon.com/hubfs/downloads.innon.com/Tridium%20Niagara/Niagara4/Documents/Tridium_Niagara_4_Graphics_Guide_Documents.pdf?hsLang=en) | Standard scalable Niagara widgets and symbols | Bundled Niagara assets; use is governed by the installed Niagara license | Primary Niagara compatibility target, not a repo asset source |
| [One Sight OSS Graphics Library](https://onesight.solutions/ossgraphicslibrary-svgs-for-niagara-4-bms/) | 1,857 SVGs and 125 templates | Commercial per-device or supervisor licensing | Commercial evaluation candidate |
| [QA Graphics Vector Symbol Library](https://www.qagraphics.com/vector-symbol-lib/) | Niagara module, vector symbols, automated component assembly | Commercial license | Commercial evaluation candidate |
| [Niagara UI Marketplace](https://niagaraui.com/) | Dashboards, PX pages, UI components, reports | Product-specific commercial terms | UX reference; evaluate per product |
| [Works Software Graphics Library](https://www.wse-ltd.com/product-services/niagara/niagara-graphics-library.html) | Menus, buttons, charts, gauges, tables, controls | Host-ID or site licensing | Commercial evaluation candidate |
| [ProSystems OAS](https://www.prosystems.de/en/niagara-4-solutions/graphics-and-function-libraries/graphic-libraries.html) | Configurable HVAC and room SVG widgets | Commercial terms | Commercial evaluation candidate |
| [VYKON Reflow](https://www.vykon.com/us/en/products/reflow) | Full station UI and navigation replacement | Commercial Niagara product | UX architecture reference |
| [SlotPath Studios](https://slotpathstudios.com/) | PX templates and station-aware packaging | Commercial terms | Packaging workflow reference |

## Broader BAS Sources

| Source | Coverage | License / constraint | Decision |
| --- | --- | --- | --- |
| [Graphivac](https://hvac.io/products/graphivac) | AHUs, VAVs, chillers, boilers, pumps, fans, valves, sensors, ducts, and pipes | Free to run; the product page does not grant asset redistribution rights | Architecture and coverage reference only |
| [Computrols Free Graphics](https://www.computrols.com/building-automation-software/free-graphics-for-bas/) | Visio stencils, AHUs, chillers, pipe sensors, duct equipment, animations | Form-gated download; site states all rights reserved | Do not import without written redistribution permission |
| [BASGFX](https://www.basgfx.com/) | Modular water, air, rooftop, terminal, and exhaust systems | Commercial library | Visual coverage reference |
| [iSMA Graphics](https://www.ismacontrolli.com/en/isma-graphics.html) | More than 300 images and AHU, RTU, VAV, and FCU templates | Restricted to licensed MAC36NL use | Hardware-specific evaluation only |

## Permissive Supporting Sources

These sources can support generic interface icons, but they do not replace the
domain-specific equipment generator.

| Source | Coverage | License | Decision |
| --- | --- | --- | --- |
| [Tabler Icons](https://github.com/tabler/tabler-icons) | General UI actions and status symbols | MIT | Approved when a generic UI icon is needed |
| [Heroicons](https://github.com/tailwindlabs/heroicons) | General UI actions and status symbols | MIT | Approved when consistent with the host UI |
| [draw.io](https://github.com/jgraph/drawio) | Diagram editor and stencil framework | Apache 2.0 with an Atlassian-specific stencil restriction | Tooling reference; review each stencil family separately |
| [Inkscape Open Symbols](https://github.com/PanderMusubi/inkscape-open-symbols) | Aggregated symbol packs | Per-pack licenses vary | Do not import without per-symbol provenance |

## System Coverage

The original `fieldline` SVG system now covers:

- Built-up AHU sections and airflow.
- VAV and fan-powered terminal relationships.
- RTU and unitary equipment.
- Chilled-water supply and return.
- Condenser-water supply and return.
- Heating-water supply and return.
- Chillers, boilers, cooling towers, pumps, and heat exchangers.
- AHU load groups and terminal networks.
- Live-value, setpoint, status, command, and alarm widgets.

## Adoption Rules

1. Prefer original SVG primitives for runtime product assets.
2. Record source URL, license text, attribution, version, and asset checksum before import.
3. Keep customer-licensed Niagara packages in a gitignored deployment directory.
4. Reject sources that only say "free" without granting redistribution rights.
5. Keep operational state in data widgets and process color, not decorative equipment color.
6. Reserve red for actionable alarm state.
