# Graphics Asset Reference Map

Reviewed: July 17, 2026

Purpose: curate official manufacturer references that match the current BAS assistant graphic style and can be used to improve proportions, section sequencing, service details, and recognizable component geometry without copying vendor art directly.

## Primary Visual Families

- `AAON`, `Daikin Applied`, and `Carrier Commercial` for AHU and RTU cabinet language.
- `Greenheck` and `Twin City Fan` for dampers, plenum fans, housed fans, and fan-array details.
- `AAF`, `Camfil`, and commercial air-handler product pages for filter and coil section treatment.
- `Condair` and `Fresh-Aire UV` for humidification and UV accessory geometry.
- `Nailor` for sound attenuator / splitter silencer proportions.
- `Xylem Bell & Gossett` for pump silhouettes and motor/volute relationships.
- `Daikin Applied`, `Cleaver-Brooks`, and `SPX Cooling Technologies` for central-plant equipment.
- `Price Industries` for VAV terminal-unit casing and reheat/fan-powered detail language.

## Asset Map

| Asset ID | Primary Reference | URL | Why it fits |
| --- | --- | --- | --- |
| `ahu_drawthrough_doubledeck` | AAON H3 Series | https://www.aaon.com/products/h3-series | Strong double-wall cabinet proportions, access-door rhythm, and plenum-fan AHU sectioning. |
| `rtu_packaged_rooftop` | AAON RN Series | https://www.aaon.com/products/rn-series | Good packaged rooftop silhouette, condenser-fan placement, and service-panel language. |
| `mixing_damper_bank` | Greenheck Control Dampers | https://www.greenheck.com/products/air-control/dampers/control-dampers | Good blade/frame/linkage proportions for outside-air and mixed-air sections. |
| `mixing_damper_low_leak` | Greenheck VCD-34 | https://www.greenheck.com/products/air-control/dampers/control/vcd-34 | Better low-leak / airfoil-blade direction than generic damper art. |
| `filter_bank_vcell` | AAF V-Bank Filters | https://aafintl.com/en/commercial/products/air-filters/v-bank-filters | Clean V-cell pack geometry for deep final-filter sections. |
| `filter_bank_bag` | AAF Bag Filters | https://aafintl.com/en/commercial/products/air-filters/bag-filters | Good pocket depth and header spacing reference. |
| `filter_bank_panel` | Camfil Panel Filters | https://www.camfil.com/en-us/products/general-ventilation-filters/panel-filters | Useful flat prefilter and pleated panel treatment. |
| `cooling_coil_chw` | Carrier 39DC | https://www.carrier.com/us/en/commercial/airside/39dc/ | Explicit commercial cooling-coil construction with serviceable air-handler framing. |
| `cooling_coil_dx` | Carrier 39HX | https://www.carrier.com/commercial/en/se/products/air-treatment/air-handling-units/compact/39hx/ | Explicit official DX-coil reference with copper tube / aluminum fin language. |
| `heating_coil_hw` | Daikin Applied Custom Air Handlers | https://www.daikinapplied.com/products/air-handlers/custom-air-handler | Good commercial coil-bay spacing and heating-coil integration language. |
| `heating_coil_steam` | Carrier Gemini 40RLQ | https://www.carrier.com/commercial/en/us/products/split-systems-and-condensers/split-systems/40rlq/ | Official packaged air handler page that explicitly includes steam-coil options. |
| `supply_fan_scroll` | Twin City Fan Centrifugal Fans | https://www.tcf.com/products/centrifugal-fans | Best source for housed wheel, cutoff, volute, and external motor proportions. |
| `supply_fan_plenum` | Greenheck HPA Direct Drive Plenum Fan | https://www.greenheck.com/products/fans/fan-arrays/hpa | Better direct-drive fan-array / plenum-fan reference than generic wheel symbols. |
| `relief_fan_housed` | Twin City Fan Centrifugal Fans | https://www.tcf.com/products/centrifugal-fans | Good return/relief housed-fan casing and wheel/motor arrangement. |
| `steam_humidifier_grid` | Condair Steam Distribution | https://www.condair.com/en/products/system-components-and-accessories/steam-distribution | Good manifold, tube-bank, and duct-mounted steam-distributor geometry. |
| `energy_recovery_wheel` | SEMCO True 3A Wheel | https://www.semcohvac.com/wheels/true-3a | Strong cassette, hub, wheel, and purge-section language for ERV sections. |
| `uv_c_lamp_bank` | Fresh-Aire UV Commercial HVAC | https://www.freshaireuv.com/commercial-hvac/ | Good lamp-rack and service-frame geometry for in-duct UV-C sections. |
| `sound_attenuator_baffle` | Nailor Silencers | https://nailor.com/products/silencers | Clear splitter-baffle silencer proportions and perforated-liner treatment. |
| `rectangular_supply_duct` | SMACNA Rectangular Duct Construction | https://shop.smacna.org/smacna-rectangular-industrial-duct-construction-standards.html | Best standards-grounded reference for rectangular duct seams and stiffening logic. |
| `chiller_air_cooled` | Daikin Pathfinder Air-Cooled Screw Chiller | https://www.daikinapplied.com/products/chiller-products/pathfinder | Good top-fan, coil-wall, and packaged skid proportions. |
| `boiler_condensing` | Cleaver-Brooks ClearFire-CE | https://cleaverbrooks.com/Product/cfce | Strong floor-mounted condensing-boiler cabinet, burner-door, and vent geometry. |
| `pump_end_suction` | Bell & Gossett e-1510X | https://www.xylem.com/en-us/products--services/pumps-packaged-pump-systems/pumps/end-suction-pumps/e-1510x-smart-pumps/ | Best official end-suction pump source in the current style family. |
| `cooling_tower_open_cell` | SPX Marley NC | https://spxcooling.com/cooling-towers/marley-nc/ | Strong basin, casing, fill section, and induced-draft fan-cylinder proportions. |
| `chiller_centrifugal_water_cooled` | Daikin Magnitude | https://www.daikinapplied.com/products/chiller-products/magnitude | Strong barrel/chassis/compressor proportions for modern water-cooled chillers. |
| `boiler_firetube` | Cleaver-Brooks CBEX Firetube Boiler | https://www.cleaverbrooks.com/Product/cbex | Best current firetube reference for horizontal shell, burner front, and trim layout. |
| `pump_vertical_inline` | Bell & Gossett Series e-90 ECM | https://www.xylem.com/en-us/products--services/pumps-packaged-pump-systems/pumps/in-line-pumps/series-e-90-ecm-small-close-coupled-in-line-centrifugal-pumps-with-ecm-motors/ | Good inline body, motor can, and flange relationships. |
| `cooling_tower_induced_draft` | SPX Marley NC | https://spxcooling.com/cooling-towers/marley-nc/ | Strong induced-draft fan stack and casing proportions for package towers. |
| `vav_reheat_terminal` | Price FDC/FPC Series Flow Fan Powered Terminal Unit | https://priceindustries.com/product/fdc-fpc-constant-volume-series-flow | Strong VAV casing, fan-powered geometry, and reheat-option language. |

## Redesign Priority

Prioritize these first because they have the biggest impact on perceived realism:

1. `supply_fan_scroll`
2. `supply_fan_plenum`
3. `mixing_damper_bank`
4. `mixing_damper_low_leak`
5. `filter_bank_vcell`
6. `cooling_coil_chw`
7. `cooling_coil_dx`
8. `vav_reheat_terminal`

## Guidance

- Use these sources for proportion, access-door placement, blade spacing, wheel depth, fin density, and component relationships.
- Avoid tracing vendor art or recreating logos, labels, or exact marketing compositions.
- Keep the repo’s current simplified industrial rendering style, but push it toward more believable section internals and service-side detailing.
