import os
import json
import tempfile
import base64
import anthropic
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, TranscriptionUsage
from routes.inspections import _AS_INVENTORY_RE

transcribe_bp = Blueprint('transcribe', __name__)


# ── JSON safety ────────────────────────────────────────────────────────────
def _sanitise_json(s: str) -> str:
    """
    Claude occasionally emits literal control characters (real newlines,
    tabs, carriage returns) inside JSON string values instead of the
    escaped sequences \\n / \\t / \\r.  These are technically invalid JSON
    and cause json.loads to raise JSONDecodeError.

    This function walks the raw string character-by-character and replaces
    any bare control character found *inside* a JSON string with its
    correctly-escaped counterpart, leaving the structural characters
    (newlines between keys, etc.) untouched.
    """
    result = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


# ── Whisper transcript post-corrections ───────────────────────────────────
# Whisper consistently mishears certain property-inspection terms.
# Apply these substitutions after transcription, before Claude sees the text.
import re as _re
_TRANSCRIPT_CORRECTIONS = [
    # Technical terms
    (_re.compile(r'\bcereal number\b', _re.I),    'serial number'),
    (_re.compile(r'\bserial numbers?\b', _re.I),  'serial number'),  # normalise
    (_re.compile(r'\bse real number\b', _re.I),   'serial number'),
    (_re.compile(r'\bsiren number\b', _re.I),     'serial number'),
    (_re.compile(r'\bwhite goods\b', _re.I),      'white goods'),    # keep as-is (just pin)
    # Common dictation mishearings
    (_re.compile(r'\bwarm and tare\b', _re.I),    'fair wear and tear'),
    (_re.compile(r'\bwhere and tare\b', _re.I),   'fair wear and tear'),
    (_re.compile(r'\bwear and tare\b', _re.I),    'fair wear and tear'),
    (_re.compile(r'\bfair wear and tear\b', _re.I), 'fair wear and tear'),  # pin
    (_re.compile(r'\bcoving\b', _re.I),           'coving'),
    (_re.compile(r'\bcorving\b', _re.I),          'coving'),
    (_re.compile(r'\bskirting board\b', _re.I),   'skirting board'),
    (_re.compile(r'\bskirting boards?\b', _re.I), 'skirting board'),
    (_re.compile(r'\barchitrave\b', _re.I),       'architrave'),
    (_re.compile(r'\bark it trave\b', _re.I),     'architrave'),
    (_re.compile(r'\binduction hob\b', _re.I),    'induction hob'),
    (_re.compile(r'\bextractor fan\b', _re.I),    'extractor fan'),
    (_re.compile(r'\bextractor\b', _re.I),        'extractor'),
    (_re.compile(r'\bthermostatic\b', _re.I),     'thermostatic'),
    (_re.compile(r'\bthermostat ic\b', _re.I),    'thermostatic'),
    (_re.compile(r'\bTRV\b', _re.I),              'TRV'),
    (_re.compile(r'\bdouble glazed\b', _re.I),    'double glazed'),
    (_re.compile(r'\bUPVC\b', _re.I),             'UPVC'),
    (_re.compile(r'\byou PVC\b', _re.I),          'UPVC'),
    (_re.compile(r'\bu PVC\b', _re.I),            'UPVC'),
    # Normalise compound words to standard UK one-word forms
    (_re.compile(r'\blime\s+scale\b', _re.I),     'limescale'),
    # Normalise "add sub-item" variants → canonical trigger phrase "add sub item"
    (_re.compile(r'\badd sub-items?\b', _re.I),   'add sub item'),
    (_re.compile(r'\badd subitems?\b', _re.I),    'add sub item'),
    (_re.compile(r'\badd a sub-?item\b', _re.I),  'add sub item'),
    # Normalise "not seen" variants (Whisper mishearing)
    (_re.compile(r'\bnot scene\b', _re.I),        'not seen'),
    # Normalise "rawl plug" (Whisper writes "raw plug" or "rawl plug" inconsistently)
    (_re.compile(r'\braw\s+plug(s?)\b', _re.I),    r'rawl plug\1'),
    (_re.compile(r'\brawle?\s+plug(s?)\b', _re.I), r'rawl plug\1'),
    # "warn" → "worn" (Whisper consistently mishears the condition word "worn")
    (_re.compile(r'\bwarn\b', _re.I),              'worn'),
    # "casing window" → "casement window" (standard UK window type)
    (_re.compile(r'\bcasing\s+window(s?)\b', _re.I), r'casement window\1'),
    # Additional UPVC mishearings
    (_re.compile(r'\bEPEZ\b', _re.I),              'UPVC'),
    (_re.compile(r'\bupez\b', _re.I),              'UPVC'),
    (_re.compile(r'\bU\s*P\s*V\s*C\b', _re.I),    'UPVC'),
    # Normalise "delete item" variants (hyphen / spacing)
    (_re.compile(r'\bdelete-item\b', _re.I),      'delete item'),
]

def _correct_transcript(text: str) -> str:
    """Apply known Whisper mishearing corrections for property inspection vocabulary."""
    for pattern, replacement in _TRANSCRIPT_CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text


# ── Inspection vocabulary dictionaries ────────────────────────────────────
# Injected into AI prompts so the model reliably recognises condition signals
# and description terms across all property inspection item types.

_CONDITION_WORDS = """
══════════════════════════════════════════════════════
CONDITION VOCABULARY — all recognised condition signals
══════════════════════════════════════════════════════
Everything below signals CONDITION, not description.
Once any of these appears, everything from that word onwards is condition.

State grades:
  In good order / Good order / In very good order / In excellent order / As new / As inventory / As found
  In fair order / Fair order / Some wear / Light wear / Light surface wear / Fair wear and tear
  In poor order / Poor order / Heavily worn / Well worn

Magnitude qualifiers (appear before a defect word — the whole phrase is condition):
  Light / Slight / Minor / Superficial / Moderate / Heavy / Severe / Extensive / Significant / Notable

Surface defects:
  Scuff / Scuffs / Scuffed / Scuffing / Light scuffing / Scuff mark / Scuff marks
  Scratch / Scratches / Scratched / Scratching / Light scratching / Surface scratching / Light surface scratching
  Mark / Marks / Marked / Marking / Light marking / Light marks / Light surface marks
  Impact mark / Impact marks (from door handle, furniture, etc.)
  Chip / Chips / Chipped / Chipping / Small chip / Large chip
  Crack / Cracks / Cracked / Cracking / Hairline / Hairline crack / Fine crack / Stress crack / Settlement crack / Crazing
  Dent / Dents / Dented / Denting
  Indentation / Indented / Indentation mark / Indentation marks (pressed-in area, e.g. from furniture feet)
  Gouge / Gouges / Gouged / Nick / Nicks / Nicked / Notch / Notches / Score / Scored
  Hole / Holes / Small hole / Large hole

Finish defects:
  Stain / Stains / Stained / Staining / Light staining / Tide mark / Water mark / Water stain
  Nicotine / Nicotine staining (discolouration from cigarette smoke)
  Soot / Soot mark / Soot marks / Soot staining (from fire, candles, or smoke)
  Grease / Grease mark / Grease marks / Grease build-up (surface contamination)
  Burn / Burns / Burned / Burnt / Burn mark / Scorch / Scorched / Scorching / Scorch mark
  Discolouration / Discoloured / Yellowing / Yellowed / Fading / Faded / Bleached

Surface deterioration:
  Peeling / Peeled / Peel / Paint peeling / Flaking / Flaked / Flake / Flaky
  Bubbling / Bubbled / Blistering / Blistered
  Warping / Warped / Bowing / Bowed / Buckling / Buckled
  Sagging / Sagged / Splitting / Split / Tearing / Torn / Fraying / Frayed
  Lifting / Lifted / Lifting at edges / Lifting to edges (flooring lifting from subfloor)
  Curling / Curled / Curling at edges (vinyl or lino edges lifting)
  Delamination / Delaminating / Delaminated (surface layers separating)

Soiling:
  Dirty / Soiled / Soiling / Grimy / Greasy / Dusty
  Mould / Mouldy / Mildew / Mildewed / Black mould / Mould growth
  Damp / Dampness / Water damage / Water ingress
  Limescale / Scale / Scaling / Scale build-up / Ingrained dirt

Metal defects:
  Rust / Rusted / Rusty / Rusting / Corrosion / Corroded / Corroding / Tarnished / Tarnishing / Pitting / Pitted

Hardware / fitting defects:
  Loose / Slightly loose / Very loose / Coming loose
  Tight / Stiff / Sticky / Binding / Catching / Difficult to operate / Sticking / Stuck / Seized / Jammed
  Missing / Absent / Not present
  Broken / Snapped / Fractured / Shattered
  Bent / Misaligned / Off-square / Dropped / Dropped hinge
  Rattling / Rattle / Squeaking / Squeak / Creaking / Creak / Damaged / Worn / Heavily worn

Grout & silicone:
  Cracked grout / Missing grout / Discoloured grout / Mouldy grout
  Failed silicone / Cracked silicone / Discoloured silicone / Mouldy silicone / Deteriorating silicone

Functional observations (always condition, never description):
  Tested / Tested for power / Tested for function / Tested and working / Working / Not working
  Appears working / Appears complete / Appear complete / Appears functional / Operated / Does not operate
  Note / Noted / Please note / Worth noting

Alterations & fixings (always condition — items fitted to a surface indicate alteration or damage):
  Nail / Nails / Nail hole / Nail holes / Nail mark / Nail marks
  Screw / Screws / Screw hole / Screw holes
  Hook / Hooks / Picture hook / Picture hooks
  Rawl plug / Rawl plugs / Plug hole / Plug holes
  Blu-Tack / Blu-tack mark / Blu-tack marks / Tack mark / Tack marks
  Removal mark / Removal marks / Removal hole / Removal holes
  Cabling / Cable / Cables (when attached to a surface)
  Fitted to / Fitted at / Fixed to / Attached to / Attached / Secured to
  Tape / Tape mark / Tape marks / Tape removal mark / Adhesive mark / Adhesive residue / Sticker mark

Surface observations (always condition — present on a surface but not part of its original specification):
  Seam / Seams / Seam visible / Seams visible (repair lines or joins in plaster/wallpaper/flooring)
  Gapping / Gaps / Gap (separation between boards, tiles, or panels)
  Swelling / Swollen (raised or deformed surface area)
  Patchy / Patchiness / Patchy marks / Patchy paint (uneven surface treatment)
  Spatter / Spatter marks / Overspray / Paint spatter
  Overpainted / Over-painted / Overpaint (subsequent layers applied over original)
  Condensation / Condensation between panes / Blown unit / Misted / Fogged (glazing failure)
  Damp patch / Damp patches / Water patch / Tide mark / Tide marks
  Efflorescence / Salt deposit / Salt staining
"""

_DESCRIPTION_VOCABULARY = """
══════════════════════════════════════════════════════
DESCRIPTION VOCABULARY — recognised terms by item type
══════════════════════════════════════════════════════
Use this as a reference to correctly parse description content.
Always use the clerk's exact words — this list shows what typical descriptions contain.

DOORS & FRAMES:
  white painted / painted / stained / varnished / lacquered / natural / bare wood / MDF / solid wood /
  hollow core / pine / oak / hardwood / softwood / composite / fire door / FD30 / FD60 /
  flush / panelled / two-panel / four-panel / six-panel / glazed / part-glazed / frosted glass /
  half-glazed / fully glazed / stable door / bi-fold / sliding / French doors / double door / single door /
  architrave / door frame / door lining / door stop / threshold / draught excluder / UPVC frame /
  timber frame / aluminium frame

DOOR FITTINGS:
  lever handle / knob handle / D-handle / pull handle / bar handle / chrome / brushed chrome /
  satin chrome / brushed nickel / brass / antique brass / gold / black / pewter / white / stainless steel /
  latch / deadlock / mortice lock / rim lock / night latch / Yale lock / multipoint lock /
  euro cylinder / thumb turn / bathroom lock / WC lock / privacy lock /
  barrel bolt / flush bolt / security bolt / chain / door chain / door knob / escutcheon /
  kicking plate / kick plate / finger plate / push plate / self-closing mechanism /
  magnetic catch / roller catch / ball catch

CEILING:
  smooth plaster / plastered / artex / textured / Artex / coving / cornicing / cornice / ceiling rose /
  polystyrene tiles / suspended / plasterboard / painted / white / cream / emulsion /
  loft hatch / loft access / trap door / attic hatch / access panel / bulkhead / boxed-in /
  recessed / flat / vaulted / sloped / pitched / slanted

LIGHTING:
  pendant light / pendant fitting / ceiling light / ceiling fitting / light fitting / wall light /
  spotlight / recessed spotlight / recessed light / downlight / batten light / strip light /
  fluorescent light / LED strip / track lighting / chandelier / lantern / reading light /
  PIR light / motion sensor light / lampshade / shade / diffuser / glass shade / fabric shade /
  drum shade / globe / flex / rose / pull cord / dimmer switch / bulb / LED bulb /
  bayonet / BC / screw fit / GU10 / halogen

WALLS:
  painted / emulsion / matt emulsion / silk emulsion / satin / gloss / painted plaster /
  wallpaper / patterned wallpaper / plain wallpaper / woodchip / vinyl wallpaper /
  feature wall / tiled / part-tiled / panelled / tongue and groove / wainscot /
  dado rail / picture rail / artex / textured finish / smooth plaster / dry-lined / skim coat /
  white / cream / magnolia / off-white / grey / light grey / beige / neutral

WINDOWS & FRAMES:
  UPVC / timber / softwood / hardwood / oak / pine / aluminium / steel / composite /
  painted / white / brown / anthracite / grey / black / natural / stained / varnished /
  double glazed / triple glazed / single glazed / obscure / frosted / safety glass / toughened glass /
  sealed unit / misted unit / Georgian bar / leaded glass /
  handle / espagnolette handle / locking handle / sash lock / cockspur handle /
  stay / casement stay / sash lift / friction stay / trickle vent / ventilator /
  casement / sash / sash and case / tilt and turn / bay window / bow window /
  skylight / Velux / roof light / dormer / fixed light / transom / fanlight

CURTAINS & BLINDS:
  curtain / curtains / pair of curtains / single curtain / tab top / eyelet / pencil pleat /
  pinch pleat / ring top / voile / net curtain / lining / unlined / blackout / thermal /
  curtain rail / curtain pole / wooden pole / metal pole / chrome pole / track / pelmet /
  valance / bay pole / fascia / finial / bracket / ring / runner /
  roller blind / Roman blind / Venetian blind / vertical blind / pleated blind / cellular blind /
  blackout blind / wooden blind / timber blind / aluminium blind / fabric blind /
  fabric / linen / cotton / polyester / velvet / patterned / plain / striped / floral

HEATING:
  radiator / panel radiator / column radiator / towel radiator / heated towel rail /
  ladder towel rail / single panel / double panel / single convector / double convector /
  compact radiator / low surface temperature / LST radiator /
  TRV / thermostatic radiator valve / lock shield valve / wheelhead / manual valve /
  electric panel heater / storage heater / underfloor heating / UFH / thermostat /
  combi boiler / water cylinder / pressurised cylinder / immersion heater /
  boiler cupboard / airing cupboard / room thermostat / Hive / Nest / smart thermostat

BUILT-IN STORAGE:
  fitted wardrobe / built-in wardrobe / wardrobe / sliding wardrobe / sliding door wardrobe /
  fitted cupboard / built-in cupboard / alcove cupboard / understairs cupboard / airing cupboard /
  larder cupboard / pantry / linen cupboard / fitted shelving / alcove shelving / fitted bookcase /
  shelf / shelves / hanging rail / hanging space / rail / hook / hooks / drawer / drawers /
  sliding door / mirrored door / mirror door / internal light / basket / wire basket / divider /
  white / painted / MDF / pine / gloss / matt / mirror / mirrored / smoked mirror / glass

SWITCHES & SOCKETS:
  single socket / double socket / twin socket / USB socket / USB-A / USB-C /
  coaxial socket / TV aerial socket / telephone socket / data socket / ethernet socket /
  satellite socket / shaver socket / shaver point /
  light switch / single switch / double switch / dimmer switch / timer switch /
  pull cord / ceiling pull cord / isolator switch / extractor fan switch / fused spur /
  consumer unit / fuse box / MCB / RCD / RCBO / circuit breaker / fuse board /
  electric meter / gas meter / smart meter /
  white / chrome / brushed chrome / nickel / brushed nickel / brass / black / stainless steel / flat plate

WOODWORK:
  skirting board / skirting / architrave / door architrave / window board / window sill /
  window reveal / dado rail / picture rail / coving / cornice / beading / ovolo / torus /
  ogee / bullnose / half-round / chamfered / pencil round / quad / Scotia / batten /
  shelf / shelving / mantelpiece / mantel / chimney breast / fireplace surround /
  painted / gloss / satinwood / eggshell / primer / undercoat / white / cream /
  wood-stained / varnished / natural / bare / stripped / MDF / pine / hardwood

FLOORING:
  carpet / fitted carpet / carpet tile / laminate / laminate flooring / engineered wood /
  engineered hardwood / solid hardwood / parquet / parquet flooring / herringbone /
  luxury vinyl tile / LVT / vinyl / sheet vinyl / safety vinyl /
  ceramic tile / floor tile / porcelain tile / encaustic tile / quarry tile / stone tile /
  slate / travertine / marble / natural stone / resin / polished concrete /
  underlay / gripper rod / threshold / door bar / transition strip / metal threshold /
  silver threshold / brass threshold / inlay / border / rug / mat / doormat

FURNITURE:
  bed / single bed / double bed / king size bed / super king bed / divan / bed frame / headboard /
  ottoman / chest of drawers / dressing table / bedside table / bedside cabinet / wardrobe /
  free-standing wardrobe / mirror / full-length mirror / blanket box / bunk bed /
  sofa / two-seater sofa / three-seater sofa / corner sofa / L-shaped sofa /
  armchair / chair / recliner / footstool / coffee table / side table / occasional table /
  TV unit / media unit / entertainment unit / bookcase / shelving unit / sideboard /
  display cabinet / dining table / dining chair / dining set / desk / office chair / filing cabinet /
  coat rack / coat stand / hat stand / umbrella stand / picture / artwork / print / clock /
  wood / solid wood / pine / oak / walnut / beech / MDF / painted / lacquered /
  upholstered / fabric / leather / faux leather / velvet / rattan / wicker / metal / steel / glass

SINK & TAPS:
  ceramic sink / stainless steel sink / butler sink / Belfast sink / farmhouse sink /
  single bowl sink / double bowl sink / 1.5 bowl sink / inset sink / undermount sink /
  drainer / draining board / integral draining board / waste / plug hole /
  kitchen tap / mixer tap / single lever tap / two-handle tap / pillar tap / monobloc tap /
  pullout tap / spray tap / boiling water tap / filter tap / Quooker /
  Grohe / Hansgrohe / Franke / Armitage Shanks /
  chrome / brushed chrome / brushed nickel / black / brushed brass / gold / gunmetal / white

KITCHEN WALL UNITS:
  wall unit / wall cabinet / wall cupboard / eye-level unit / larder unit /
  single door wall unit / double door wall unit / corner wall unit / glass door unit /
  display unit / wine rack / plate rack / open shelf unit /
  shelf / shelves / door / doors / glass door / soft-close hinge / bar handle / knob /
  integrated handle / push-to-open / push latch

KITCHEN BASE UNITS:
  base unit / base cabinet / floor unit / cupboard / larder unit / larder cupboard /
  pan drawer / drawer pack / three-drawer pack / four-drawer pack / corner base unit /
  pull-out unit / carousel / lazy Susan / sink unit / hob unit / tall unit / tower unit /
  oven housing / oven tower / pantry unit / integrated appliance unit /
  shelf / shelves / door / doors / drawer / drawers / soft-close drawer / soft-close door /
  bar handle / D-handle / knob / integrated handle / push-to-open /
  gloss / matt / satin / handleless / shaker / slab / in-frame / painted /
  white / grey / cream / navy / sage green / blue / black / walnut effect / oak effect / high gloss /
  plinth / kickboard / kick board / toe kick / plinth panel /
  white carcass / grey carcass / birch carcass

WORKTOPS:
  laminate worktop / laminate / solid wood worktop / oak worktop / beech worktop / walnut worktop /
  bamboo worktop / granite worktop / granite / marble worktop / marble /
  quartz worktop / quartz / Corian / solid surface / composite worktop /
  ceramic worktop / porcelain worktop / stainless steel worktop / compact laminate /
  upstand / splashback / matching upstand / worktop upstand /
  square edge / post-formed edge / bullnose edge / bevelled edge / waterfall edge / mitre joint / end cap

SMOKE ALARMS:
  smoke alarm / smoke detector / optical smoke alarm / ionisation smoke alarm /
  heat alarm / heat detector / combined smoke and heat alarm / interlinked alarm /
  mains-powered alarm / battery-powered alarm / sealed battery alarm / 10-year alarm /
  Aico / Kidde / FireAngel / BRK / First Alert / Nest Protect / Google Nest /
  Honeywell / Hochiki / EI Electronics / ESP / Ei650 / Ei3016

CARBON MONOXIDE ALARMS:
  carbon monoxide alarm / CO alarm / CO detector / carbon monoxide detector /
  combined smoke and CO alarm / interlinked CO alarm / mains CO alarm / battery CO alarm /
  Aico / Kidde / FireAngel / BRK / First Alert / Nest Protect / Google Nest /
  Honeywell / Ei208 / Ei3018

WASH BASINS:
  wash basin / basin / pedestal basin / hand basin / semi-pedestal basin /
  wall-mounted basin / countertop basin / vessel basin / inset basin / undermount basin /
  corner basin / cloakroom basin / small basin /
  ceramic / vitreous china / china / white /
  basin tap / mixer tap / monobloc / pillar tap / single lever / waterfall tap /
  pop-up waste / plug and chain waste / slotted waste / overflow /
  Grohe / Hansgrohe / Armitage Shanks / Ideal Standard / Roca / Duravit / Villeroy & Boch /
  pedestal / half pedestal / cloakroom shelf / vanity unit / mirror cabinet

TOILETS:
  toilet / WC / close coupled WC / back to wall WC / wall-hung WC / wall-hung toilet /
  floor-standing WC / low-level WC / high-level WC /
  concealed cistern / slimline cistern / compact WC / cloakroom WC /
  cistern / pan / seat / seat and cover / soft-close seat / quick-release seat /
  flush button / dual flush / flush plate / flush handle / flush lever / overflow pipe /
  Ideal Standard / Armitage Shanks / Roca / Duravit / Villeroy & Boch /
  RAK Ceramics / Geberit / Grohe / Hansgrohe / VitrA /
  white / cream / ceramic / vitreous china

BATH & TAPS:
  bath / bathtub / roll top bath / freestanding bath / slipper bath / straight bath /
  single-ended bath / double-ended bath / P-shaped bath / L-shaped bath / corner bath /
  whirlpool bath / shower bath / bath panel / side panel / end panel /
  bath tap / bath taps / bath mixer / bath filler / floor-standing bath tap /
  wall-mounted bath tap / overflow filler / deck-mounted / freestanding tap / pillar tap /
  shower handset / bath shower mixer / shower attachment / telephone handset /
  acrylic / steel enamel / cast iron / stone resin / solid surface /
  Ideal Standard / Armitage Shanks / Carron / Trojan / BC Designs / Victoria and Albert /
  Duravit / Villeroy & Boch / Roca / Hudson Reed / Grohe / Hansgrohe / Crosswater

SHOWER & SCREENS:
  shower enclosure / shower cubicle / walk-in shower / walk-in enclosure /
  wet room / corner shower / quadrant shower / offset quadrant / rectangular enclosure /
  pivot door / sliding door / hinged door / bi-fold door / frameless / semi-frameless / framed /
  shower tray / stone resin tray / acrylic tray / ceramic tray / low-profile tray /
  flush tray / wetroom former / linear drain / central drain /
  shower screen / bath screen / fixed screen / folding screen / hinged screen /
  shower head / fixed head / rainfall head / ceiling-mounted head / handset / shower handset /
  hose / slide rail / shower bar / thermostatic valve / thermostatic shower /
  mixer shower / electric shower / digital shower / smart shower /
  Mira / Triton / Aqualisa / Grohe / Hansgrohe / Crosswater / Hudson Reed /
  Matki / Lakes / Kudos / Roman / Daryl / Bristan / Roca / Ideal Standard / Merlyn / April

APPLIANCES (built-in & free-standing):
  oven / built-in oven / single oven / double oven / multifunction oven /
  fan oven / electric oven / gas oven / pyrolytic oven / steam oven / warming drawer /
  hob / gas hob / electric hob / induction hob / ceramic hob / solid plate hob /
  four burner / five burner / six burner / gas burner / burner / zone / ring /
  extractor / extractor fan / cooker hood / chimney hood / island hood /
  integrated extractor / canopy / air recirculation / ducted / carbon filter / grease filter /
  dishwasher / integrated dishwasher / freestanding dishwasher / slimline dishwasher /
  washing machine / integrated washing machine / washer-dryer / tumble dryer /
  condenser dryer / heat pump dryer / vented dryer / integrated dryer /
  fridge / refrigerator / fridge-freezer / American fridge-freezer / freezer /
  chest freezer / larder fridge / wine cooler / wine fridge / integrated fridge /
  integrated fridge-freezer / integrated freezer / under-counter fridge /
  microwave / combination microwave / grill microwave / built-in microwave /
  integrated coffee machine / plate warmer /
  Bosch / Siemens / Samsung / LG / Hotpoint / Indesit / Beko / Zanussi /
  AEG / Miele / Neff / Whirlpool / Smeg / Rangemaster / Lacanche / Falcon / Aga / Rayburn /
  Fisher & Paykel / Haier / Hisense / Electrolux / Liebherr / Sub-Zero / Wolf / Viking /
  Gaggenau / Bauknecht / Candy / Hoover / Stoves / Britannia / Leisure / Blomberg / Lamona /
  Baumatic / Bertazzoni / CDA

SMALL APPLIANCES:
  kettle / toaster / air fryer / blender / food processor / coffee machine / espresso machine /
  Nespresso / Dolce Gusto / stand mixer / hand mixer / hand blender / stick blender /
  bread maker / rice cooker / slow cooker / instant pot / pressure cooker / steamer /
  juicer / smoothie maker / sandwich maker / griddle / waffle maker / deep fat fryer /
  electric grill / health grill / George Foreman / vacuum cleaner / steam cleaner / steam mop /
  robot vacuum / iron / steam iron / clothes steamer / fan / tower fan / pedestal fan / desk fan /
  oil-filled radiator / fan heater / dehumidifier / air purifier / humidifier /
  Kenwood / Breville / Dualit / Russell Hobbs / DeLonghi / KitchenAid / Dyson / Shark /
  Morphy Richards / Tefal / Philips / Braun / Sage / Nutribullet / Vitamix / Magimix / Cuisinart

BATHROOM ACCESSORIES:
  towel rail / towel ring / towel bar / robe hook / coat hook /
  toilet roll holder / toothbrush holder / soap dish / soap dispenser /
  shower basket / corner shelf / glass shelf / mirror / bathroom mirror / medicine cabinet /
  shaver socket / shaver light / extractor fan / bathroom cabinet / vanity unit /
  under-sink unit / toilet brush / toilet brush holder /
  chrome / brushed chrome / nickel / brushed nickel / brass / antique brass /
  black / gunmetal / gold / white / stainless steel
"""


# ── Shared prompt rule fragments ──────────────────────────────────────────
# Consolidated from what were previously near-duplicate rule blocks repeated
# across every fill function below (UK spelling, multi-component line
# splitting, appliance formatting). Each fill function keeps its own
# numbering/bullet style around these — only the rule content is shared.
# Canonical wording is the fullest variant that existed at any call site
# (a superset, not a narrowing).

_UK_SPELLING_RULE = (
    'USE UK ENGLISH SPELLING THROUGHOUT — every word in the output must use UK spelling: '
    '"discolouration" not "discoloration", "colour" not "color", "centre" not "center", '
    '"neighbour" not "neighbor", "recognise" not "recognize", "labelled" not "labeled", '
    '"mould" not "mold", "grey" not "gray", "practise" not "practice" (verb), '
    '"limescale" not "lime scale".'
)

def _multi_component_rule(field_names: str) -> str:
    """
    Shared "use \\n not commas for multiple distinct components/observations" rule.
    field_names: human-readable description of which field(s) this applies to,
    e.g. "description or condition" or "a checkOutCondition".
    """
    return (
        f'MULTI-COMPONENT LINES — CRITICAL: when {field_names} contains more than one distinct '
        'component or observation, separate each with a newline character \\n — NEVER use commas '
        'to join them. Commas are only acceptable within a single observation '
        '(e.g. "Light scuff to base of door, left side").'
    )

_APPLIANCE_FORMATTING_RULE = (
    'APPLIANCE FORMATTING — for any appliance (washing machine, dishwasher, fridge, oven, hob, dryer, microwave, etc.):\n'
    '- Each attribute MUST be on its own line — NEVER merge them into a single line\n'
    '- Order: appliance type, then colour and brand, then model number, then serial number\n'
    '  CORRECT:   "Washing machine\\nWhite Indesit\\nModel number: WD1234\\nSerial number: AB5678"\n'
    '  INCORRECT: "White Indesit washing machine, model number WD1234, serial number AB5678"\n'
    '- Format spoken model/serial references as "Model number: X" and "Serial number: X"'
)


# ── Edit-mode detection ────────────────────────────────────────────────────
# Clerks can prefix a recording with trigger phrases to amend existing fields
# rather than filling only-if-empty.
#
# Supported commands (per-item / Instant mode):
#   "Not Applicable"         → mark item for deletion
#   "Add sub item ..."       → add a sub-item beneath the current item
#   "Amend description ..."  → overwrite description field only
#   "Amend condition ..."    → overwrite condition field only
#   "Add to description ..." → append to description field only
#   "Add to condition ..."   → append to condition field only
#   "Amend ..."              → overwrite both fields (item context is implicit)
#   "Add ..."                → append to both fields
#
# NOTE: longer/more specific phrases must come before short ones so they match first.

_EDIT_TRIGGERS = [
    # Delete commands — item is not in the property or not applicable
    ('not seen',               'delete',    None),
    ('not scene',              'delete',    None),   # common Whisper mishearing of "not seen"
    ('delete item',            'delete',    None),
    ('not applicable',         'delete',    None),
    # Sub-item command — treat transcript content as a new sub-item
    ('add sub item',           'add_sub',   None),
    # Specific field amend/add
    ('amend description',      'overwrite', 'description'),
    ('amend the description',  'overwrite', 'description'),
    ('amend condition',        'overwrite', 'condition'),
    ('amend the condition',    'overwrite', 'condition'),
    ('add to description',     'append',    'description'),
    ('add to the description', 'append',    'description'),
    ('add to condition',       'append',    'condition'),
    ('add to the condition',   'append',    'condition'),
    ('add to conditions',      'append',    'condition'),
    ('add to the conditions',  'append',    'condition'),
    # Short forms — for Instant mode where item context is implicit
    ('amend',                  'overwrite', None),
    ('add',                    'append',    None),
]

def _detect_edit_mode(transcript: str):
    """
    Check if transcript starts with an edit-mode trigger phrase.
    Returns (mode, field, cleaned_transcript).
      mode:    'overwrite' | 'append' | 'delete' | 'add_sub' | 'normal'
      field:   'description' | 'condition' | None
      cleaned: transcript with trigger phrase stripped
    """
    lower = transcript.lower().strip()
    for phrase, mode, field in _EDIT_TRIGGERS:
        if lower.startswith(phrase):
            cleaned = transcript[len(phrase):].lstrip(' ,.:-').strip()
            return mode, field, cleaned
    return 'normal', None, transcript


# ── Helpers ────────────────────────────────────────────────────────────────

def _whisper_transcribe(audio_bytes: bytes, mime_type: str) -> tuple[str, float]:
    """
    Send audio bytes to OpenAI Whisper, return (transcript, duration_seconds).
    Uses verbose_json to get actual duration rather than estimating from byte count.
    """
    import openai

    client = openai.OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

    ext_map = {
        'audio/webm':  'webm',
        'audio/ogg':   'ogg',
        'audio/mp4':   'mp4',
        'audio/mpeg':  'mp3',
        'audio/mp3':   'mp3',
        'audio/wav':   'wav',
        'audio/x-wav': 'wav',
        'audio/flac':  'flac',
        'audio/m4a':   'm4a',
        'audio/aac':   'm4a',
        'video/webm':  'webm',  # some browsers report video/webm for audio
    }
    # Strip codec suffix e.g. "audio/webm;codecs=opus" → "audio/webm"
    mime_base = mime_type.split(';')[0].strip().lower() if mime_type else 'audio/webm'
    ext = ext_map.get(mime_base, 'webm')
    print(f'[transcribe] mime_base: {repr(mime_base)} → ext: {ext}')

    with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, 'rb') as f:
            response = client.audio.transcriptions.create(
                model='whisper-1',
                file=f,
                language='en',
                response_format='verbose_json',
                prompt=(
                    'UK property inventory inspection dictation. '
                    'Speaker describes item appearance and condition. '
                    'Key vocabulary: serial number, skirting board, coving, architrave, '
                    'induction hob, extractor fan, UPVC, double glazed, thermostatic, TRV, '
                    'fair wear and tear, in good order, in fair order, in poor order. '
                    'Commands to preserve exactly: '
                    '"Delete item", "Not Applicable", "Not seen", "Add sub item", '
                    '"Amend description", "Amend condition", '
                    '"Add to description", "Add to condition", "Amend", "Add". '
                    'Transcribe all words accurately, including technical property terms.'
                )
            )
        raw_transcript = str(response.text).strip()
        duration_seconds = float(response.duration or 0)
        return _correct_transcript(raw_transcript), duration_seconds
    finally:
        os.unlink(tmp_path)


def _claude_fill_item(transcript: str, item_label: str, room_name: str, section_type: str = 'room', edit_mode: str = 'normal', is_check_out: bool = False, is_damage_report: bool = False) -> dict:
    """
    Given a short transcript for a single item, return the appropriate fields
    based on section type. Uses claude-haiku-4-5.

    Section types and their fields:
    - room (default):        { description, condition }
    - condition_summary:     { condition }
    - cleaning_summary:      { notes }
    - fire_door_safety:      { notes }
    - health_safety:         { notes }
    - keys:                  { description }
    - meter_readings:        { locationSerial, reading }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    # ── Check-out per-item mode — verbatim, no splitting ───────────────────────
    # The mobile side handles the "As Inventory+" prefix; we just need the
    # clerk's exact words returned in "condition" with fillers removed.
    if is_check_out and section_type == 'room':
        co_prompt = f"""You are processing a UK property CHECK-OUT inspection dictation.
The clerk is describing the condition of a single item at the END of the tenancy.

Item: {item_label}
Room: {room_name}

The clerk said:
"{transcript}"

VERBATIM RULES — absolute, no exceptions:
- Return the COMPLETE transcript in "condition", exactly as spoken
- ONLY remove filler sounds: um, uh, er, errr, umm, erm, and clear false starts (e.g. "white — white door" → "white door")
- Do NOT interpret, condense, split, or restructure anything
- Do NOT apply description/condition splitting — everything goes into "condition"
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two bulbs" → "2 x bulbs"
- Capitalise the first word of each observation
- {_UK_SPELLING_RULE}
- {_multi_component_rule("the condition field")}

Return ONLY valid JSON, no markdown:
{{"condition": "..."}}"""
        message = client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=200,
            messages=[{'role': 'user', 'content': co_prompt}]
        )
        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        return json.loads(_sanitise_json(raw)), message

    # ── Damage Report per-item mode — verbatim, condition only ─────────────────
    if is_damage_report and section_type == 'room':
        dmg_prompt = f"""You are processing a UK property DAMAGE REPORT inspection dictation.
The clerk is describing the damage to a single item.

Item: {item_label}
Room: {room_name}

The clerk said:
"{transcript}"

RULES — absolute, no exceptions:
- Return the COMPLETE transcript in "condition" — there is NO description field in a damage report
- ONLY remove filler sounds: um, uh, er, errr, umm, erm, and clear false starts
- Do NOT interpret, condense, or paraphrase — use the clerk's exact words
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two marks" → "2 x marks"
- Capitalise the first word of each line
- {_UK_SPELLING_RULE}
- {_multi_component_rule("the condition field")}

Return ONLY valid JSON, no markdown:
{{"condition": "..."}}"""
        message = client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=200,
            messages=[{'role': 'user', 'content': dmg_prompt}]
        )
        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        return json.loads(_sanitise_json(raw)), message

    # Shared formatting rules applied to all section types
    formatting_rules = """
FORMATTING RULES — apply to all output fields:
- Convert spoken numbers to numerals: "two" → "2", "three" → "3", "one" → "1" etc.
- Format quantities as "N x item": "two green curtains" → "2 x green curtains"
- When multiple distinct items are listed, put each on its own line
- For meter readings location: use line breaks for clarity, e.g.:
    "Located to entrance hallway cupboard\nSerial Number: 123456"
- Capitalise the first word of each line
- Do NOT use bullet points or dashes — just line breaks between items
- Keep each line concise"""

    if section_type == 'meter_readings':
        field_instructions = """Extract into these two fields:
- locationSerial: where the meter is located and its serial number, formatted across lines:
    "Located to [location]\nSerial Number: [number]"
  If only location mentioned, just the location. If only serial, just the serial.
- reading: the meter reading value only (e.g. "12345")
Return ONLY valid JSON, no markdown:
{"locationSerial": "...", "reading": ""}"""

    elif section_type == 'cleaning_summary':
        field_instructions = """Put the complete transcript (cleaned of filler words only) into cleanlinessNotes.
If multiple points are made, put each on its own line using \n.
Return ONLY valid JSON, no markdown:
{"cleanlinessNotes": "..."}"""

    elif section_type in ('fire_door_safety', 'health_safety', 'smoke_alarms'):
        field_instructions = """Put the complete transcript (cleaned of filler words only) into notes.
If multiple points are made, put each on its own line using \n.
Return ONLY valid JSON, no markdown:
{"notes": "..."}"""

    elif section_type == 'condition_summary':
        field_instructions = """Put the complete transcript (cleaned of filler words only) into condition.
If multiple points are made, put each on its own line.
Return ONLY valid JSON, no markdown:
{"condition": "..."}"""

    elif section_type == 'keys':
        field_instructions = """Put the complete transcript into the description field.
Format rules:
- If the clerk mentions anything about collecting, receiving, handing over, or returning keys — regardless of who from or to — put this EXACTLY as spoken on the FIRST line. This line must always be included when the clerk says it.
  Examples: "Keys collected from and returned to Yellands Estates", "Keys handed to tenant", "Keys received from landlord", "Keys collected from client and returned to office"
- Each key type goes on its own line using \\n, formatted as "N x [key type]"
  Example: "1 x Yale key\\n1 x Chubb key\\n2 x garage fob"
- Convert spoken numbers to numerals: "one" → "1", "two" → "2"
- Use "x" not "×" for quantities
Return ONLY valid JSON, no markdown:
{"description": "..."}"""

    else:
        # "Add sub item" mode — clerk is adding a sub-item to an existing item.
        # Parse description and condition from the transcript and return them
        # nested inside a _subs array so the caller knows to append, not overwrite.
        if edit_mode == 'add_sub':
            field_instructions = """The clerk is dictating a SUB-ITEM to add beneath an existing inspection item.
Extract description and condition from the transcript exactly as you would for a normal item,
then return the result inside a "_subs" array with a single entry.

Defect and state words are ALWAYS condition even when they appear without a preceding "in … order" phrase.
  Example: "chrome doorstop, slightly loose"
    → description: "Chrome doorstop"   condition: "Slightly loose"
  Example: "white door handle, missing screw"
    → description: "White door handle"   condition: "Missing screw"

If no condition is mentioned, default condition to "In good order".

""" + _multi_component_rule("description or condition") + """

""" + _CONDITION_WORDS + """
Return ONLY valid JSON, no markdown:
{"_subs": [{"description": "...", "condition": "..."}]}"""
        else:
            field_instructions = """Extract and structure this into:
- description: the physical appearance (material, colour, size, style, finish)
- condition: the state or working order

SPLITTING rules — read carefully:
- These phrases signal the START of the condition portion:
    "in good order", "in fair order", "in poor order", "good order", "fair order",
    "poor order", "as new", "as inventory", "in good condition", "in fair condition",
    "in poor condition", "some wear", "light wear", "heavy wear", "light scratches",
    "light marks", "light staining", "light surface", "surface scratching",
    "tested", "working", "functional", "appears", "appear", "note", "noted",
    "please note", "fair wear and tear"
- Everything AFTER a condition phrase is ALSO condition, not description.
  Example: "Black Beko induction hob, four burners, light surface scratching to hob plate"
    description: "Black Beko induction hob\n4 x burners"
    condition:   "Light surface scratching to hob plate"
- Functional observations ("appear complete", "tested for power", "appears working",
  "note scuff", "please note") are ALWAYS condition, never description
- Damage, marks, scratches, staining, wear = condition
- If the transcript contains ANY condition observations, use them — do NOT substitute "In good order"
- ONLY use "In good order" as a default if the clerk genuinely said nothing about condition AND
  there are no wear, damage, or observation words present

DEFAULT CONDITION RULE — this is critical:
- "In good order" is a fallback ONLY when zero condition information exists
- If the clerk said ANYTHING about appearance quality, wear, damage, or function — use their words
- WRONG: clerk says "light surface scratching" → condition: "In good order"
- RIGHT: clerk says "light surface scratching" → condition: "Light surface scratching"

""" + _multi_component_rule("description or condition") + """

""" + _APPLIANCE_FORMATTING_RULE + """
""" + _CONDITION_WORDS + """
Return ONLY valid JSON, no markdown:
{"description": "...", "condition": "..."}"""

    prompt = f"""You are processing a UK property inspection dictation.

Section type: {section_type}
Item: {item_label}
Room/Section: {room_name}

The clerk has dictated:
"{transcript}"

CRITICAL LANGUAGE RULES:
- Use the EXACT words and phrases the clerk spoke. Do not substitute synonyms, paraphrase, or condense.
- "good order" stays "good order" — never change to "good condition"
- "fair wear and tear" stays exactly that
- This is a legal document — preserve all professional terminology exactly
- ONLY remove filler sounds (um, uh, er, errr, umm, erm) — do NOT remove, shorten, or alter any actual content words
- Do NOT summarise or abbreviate what the clerk said — reproduce their words in full
- DUPLICATE SPEECH: the recording may contain repeated or restarted phrases. If the clerk
  says the same thing twice, output it once. Never repeat an observation in your output,
  and never place the same phrase in both the description and the condition fields.
- {_UK_SPELLING_RULE}
{formatting_rules}

{field_instructions}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=300,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(_sanitise_json(raw)), message

def _claude_fill_full_report(transcript: str, template_structure: dict) -> dict:
    """
    Given a long continuous transcript covering a whole inspection,
    fill all items in the template structure.

    Returns a dict matching reportData shape:
    { sectionId: { rowId: { description: "...", condition: "..." } } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    structure_json = json.dumps(template_structure, indent=2)

    prompt = f"""You are processing a UK property inventory inspection audio transcript.
The clerk has walked through the property and dictated descriptions and conditions for items room by room.

Template structure (the items that need filling):
{structure_json}

Full transcript:
"{transcript}"

Instructions:
- Map the clerk's dictation to the correct items in the template
- For each item, extract description and condition
- CRITICAL: Use the EXACT words and phrases the clerk spoke. Do not substitute synonyms or rephrase.
  Example: if the clerk says "good order", write "Good order" — NOT "Good condition"
  Example: if the clerk says "fair wear and tear", write exactly that
  Example: if the clerk says "as new" or "as inventory", preserve those exact phrases
- The clerk's terminology is professional and intentional — this is a legal document
- ONLY remove filler sounds (um, uh, er, errr, umm, erm) — do NOT remove, shorten, or alter any actual content words
- Do NOT summarise or abbreviate what the clerk said — reproduce their words in full
- DUPLICATE SPEECH: the recording may contain repeated or restarted phrases. If the clerk
  says the same thing twice, output it once. Never repeat an observation in your output,
  and never place the same phrase in both the description and the condition fields.
- {_UK_SPELLING_RULE}
- {_multi_component_rule("description or condition")}
- Only fill items that are mentioned in the transcript
- If an item is not mentioned, omit it from the output entirely

Return ONLY valid JSON in this exact shape (no markdown):
{{
  "<sectionId>": {{
    "<rowId>": {{
      "description": "...",
      "condition": "..."
    }}
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=4000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    return json.loads(_sanitise_json(raw))


# ── Endpoints ─────────────────────────────────────────────────────────────

@transcribe_bp.route('/classify-photo', methods=['OPTIONS'])
def classify_photo_options():
    return '', 204


@transcribe_bp.route('/status', methods=['GET'])
@jwt_required()
def transcribe_status():
    """Returns which AI services are configured — used by TranscriptionSettings."""
    return jsonify({
        'openai':    'ok' if os.environ.get('OPENAI_API_KEY')    else 'missing',
        'anthropic': 'ok' if os.environ.get('ANTHROPIC_API_KEY') else 'missing',
    })


@transcribe_bp.route('/item', methods=['POST'])
@jwt_required()
def transcribe_item():
    """
    Per-item clip — called immediately when a short item recording stops.

    Request JSON:
    {
      "audio":      "<base64-encoded audio>",
      "mimeType":   "audio/webm",
      "itemLabel":  "Door & Frame",
      "roomName":   "Kitchen",
      "sectionId":  "abc123",
      "rowId":      "456"
    }

    Response JSON:
    {
      "transcript":  "White painted panel door...",
      "description": "White painted panel door with chrome handle",
      "condition":   "In good order",
      "sectionId":   "abc123",
      "rowId":       "456"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    audio_b64    = data.get('audio')
    mime_type    = data.get('mimeType', 'audio/webm')
    item_label   = data.get('itemLabel', 'Item')
    room_name    = data.get('roomName', '')
    section_id   = data.get('sectionId')
    row_id       = data.get('rowId')
    section_type      = data.get('sectionType', 'room')  # room|condition_summary|cleaning_summary|keys|meter_readings|fire_door_safety|health_safety
    is_check_out      = bool(data.get('isCheckOut', False))
    is_damage_report  = bool(data.get('isDamageReport', False))

    if not audio_b64:
        return jsonify({'error': 'No audio data'}), 400

    # Debug: log what we received
    print(f'[transcribe/item] mimeType received: {repr(mime_type)}')
    print(f'[transcribe/item] audio_b64 length: {len(audio_b64)}')

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return jsonify({'error': 'Invalid base64 audio data'}), 400

    try:
        raw_transcript, audio_secs = _whisper_transcribe(audio_bytes, mime_type)

        if not raw_transcript:
            return jsonify({'error': 'No speech detected in recording'}), 422

        # Detect edit-mode trigger phrases before passing to Claude
        edit_mode, edit_field, transcript = _detect_edit_mode(raw_transcript)

        # Check Out inspections do not support delete or add-sub commands.
        # "Not seen" at check-out means the item was there at check-in but is now missing —
        # it is meaningful condition content, not a deletion trigger.
        # Items must never be deleted from a check-out report.
        if is_check_out and edit_mode in ('delete', 'add_sub'):
            edit_mode = 'normal'
            edit_field = None
            transcript = raw_transcript

        print(f'[transcribe/item] edit_mode={edit_mode!r} field={edit_field!r} transcript={transcript[:60]!r}')

        # ── Delete: "Not Applicable" — no Claude call needed ──────────────
        if edit_mode == 'delete':
            return jsonify({
                'transcript': raw_transcript,
                'editMode':   'delete',
                'editField':  None,
                'sectionId':  section_id,
                'rowId':      row_id,
                'sectionType': section_type,
            })

        filled, filled_msg = _claude_fill_item(transcript, item_label, room_name, section_type, edit_mode, is_check_out, is_damage_report)

        # Log usage
        try:
            usage = TranscriptionUsage(
                call_type     = 'item',
                inspection_id = int(data.get('inspectionId')) if data.get('inspectionId') else None,
                user_id       = int(get_jwt_identity()),
                audio_seconds = audio_secs,
                input_tokens  = filled_msg.usage.input_tokens  if filled_msg and filled_msg.usage else 0,
                output_tokens = filled_msg.usage.output_tokens if filled_msg and filled_msg.usage else 0,
                section_type  = section_type,
            )
            db.session.add(usage)
            db.session.commit()
        except Exception:
            pass  # never let logging break the response

        return jsonify({
            'transcript':       raw_transcript,   # return original for reference
            'description':      filled.get('description', ''),
            'condition':        filled.get('condition', ''),
            'notes':            filled.get('notes', ''),
            'cleanlinessNotes': filled.get('cleanlinessNotes', ''),
            'locationSerial':   filled.get('locationSerial', ''),
            'reading':          filled.get('reading', ''),
            '_subs':            filled.get('_subs', []),   # populated when "Add sub item" used
            'sectionId':        section_id,
            'rowId':            row_id,
            'sectionType':      section_type,
            'editMode':         edit_mode,    # 'normal' | 'overwrite' | 'append' | 'add_sub'
            'editField':        edit_field,   # 'description' | 'condition' | None
        })

    except Exception as e:
        import traceback
        print(f'[transcribe/item] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/classify-photo', methods=['POST'])
@jwt_required()
def classify_photo():
    """
    Accepts a base64 image and room/item context string.
    Uses Claude vision to identify which room and item the photo belongs to.

    Request JSON:
    {
      "imageBase64": "<base64 jpeg>",
      "mimeType":    "image/jpeg",
      "roomContext": "<formatted room+item list string>"
    }

    Response JSON:
    {
      "sectionKey":  "42",
      "sectionName": "Bedroom 1",
      "itemKey":     "87",
      "itemName":    "Door & Frame",
      "confidence":  0.92
    }
    """
    data = request.get_json(force=True)
    image_base64  = data.get('imageBase64', '')
    mime_type     = data.get('mimeType', 'image/jpeg')
    room_context  = data.get('roomContext', '')
    inspection_id = int(data.get('inspectionId')) if data.get('inspectionId') else None

    if not image_base64 or not room_context:
        return jsonify({'error': 'imageBase64 and roomContext are required'}), 400

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    prompt = f"""You are a property inspection assistant. Look at this photo carefully and identify which item in the room it belongs to.

{room_context}

Each item above may include a "described as" note (what the inspector has already written about it) and/or a "condition" note. Use these text descriptions alongside your visual analysis — if an item's description matches what you see in the photo, that is a strong signal.

Common property inspection items and what they look like:
- Door Fittings / Door & Frame: door handles, hinges, door frames, locks, letterboxes, door furniture
- Lighting / Light Fitting: ceiling lights, pendant lights, light shades, lampshades, wall lights, spotlights, bulbs, light fittings
- Walls: painted surfaces, wallpaper, plasterwork, wall damage, marks, dado rails
- Ceiling: ceiling surfaces, coving, cornices, ceiling roses
- Floor / Flooring: carpet, hardwood, laminate, tiles, vinyl, skirting boards
- Windows / Window & Frame: glass panes, window frames, window sills, blinds, curtains, curtain rails
- Radiator / Heating: radiators, heating units, thermostats, towel rails
- Sockets & Switches: electrical outlets, light switches, fuse boxes, consumer units
- Smoke Alarm / Carbon Monoxide Alarm: round alarm units mounted on ceiling or wall
- Kitchen appliances: oven, hob, microwave, dishwasher, fridge, extractor fan
- Bathroom: bath, shower, sink, toilet, taps, shower screen, tiles

Respond ONLY with a raw JSON object — no markdown, no backticks, no explanation, just the JSON:
{{"sectionKey":"<key>","sectionName":"<room name>","itemKey":"<key>","itemName":"<item name>","confidence":0.92}}

Rules:
- confidence is a number from 0.0 to 1.0
- Give confidence above 0.8 only when you are certain of both the room AND the item
- If an item's existing description closely matches what you see visually, increase your confidence accordingly
- If you can identify the item type but are unsure which one in the list, give 0.5-0.7
- sectionKey and itemKey must be copied exactly from the provided context list
- Match to the single closest item in the list"""

    try:
        message = client.messages.create(
            model='claude-opus-4-5',
            max_tokens=150,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type':       'base64',
                            'media_type': mime_type,
                            'data':       image_base64,
                        },
                    },
                    {
                        'type': 'text',
                        'text': prompt,
                    },
                ],
            }],
        )

        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(_sanitise_json(raw))

        # Ensure all required fields are present
        for field in ('sectionKey', 'sectionName', 'itemKey', 'itemName'):
            if field not in result:
                result[field] = ''
        result['confidence'] = float(result.get('confidence', 0))

        # Log usage
        try:
            usage_log = TranscriptionUsage(
                call_type     = 'photo',
                inspection_id = inspection_id,
                user_id       = int(get_jwt_identity()),
                audio_seconds = 0,
                input_tokens  = message.usage.input_tokens  if message.usage else 0,
                output_tokens = message.usage.output_tokens if message.usage else 0,
                section_type  = 'photo',
            )
            db.session.add(usage_log)
            db.session.commit()
        except Exception:
            pass  # never let logging break the response

        return jsonify(result)

    except json.JSONDecodeError as e:
        # Claude returned something that wasn't valid JSON — return gracefully
        print(f'[classify-photo] JSON parse error: {e}, raw: {raw!r}')
        return jsonify({
            'sectionKey': '', 'sectionName': '',
            'itemKey': '',    'itemName': '',
            'confidence': 0,
        })

    except Exception as e:
        import traceback
        print(f'[classify-photo] Error: {e}')
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@transcribe_bp.route('/usage', methods=['GET'])
@jwt_required()
def transcribe_usage():
    """Returns usage stats and cost estimates in GBP, grouped by inspection."""
    from datetime import datetime, timedelta, timezone
    from models import Inspection

    period = request.args.get('period', '30')
    since  = datetime.now(timezone.utc) - timedelta(days=int(period))
    rows   = TranscriptionUsage.query.filter(TranscriptionUsage.created_at >= since).all()

    # ── Pricing constants ──────────────────────────────────────────────────
    USD_TO_GBP            = 0.79
    WHISPER_PER_MIN_USD   = 0.006          # Whisper-1 ($0.006/min)
    HAIKU_IN_PER_1M_USD   = 1.00           # claude-haiku-4-5 input
    HAIKU_OUT_PER_1M_USD  = 5.00           # claude-haiku-4-5 output
    # Photo classification uses claude-opus-4-5 — apply Opus-tier pricing
    OPUS_IN_PER_1M_USD    = 15.00          # claude-opus-4-5 input
    OPUS_OUT_PER_1M_USD   = 75.00          # claude-opus-4-5 output
    # PDF import (extraction + redistribution) uses claude-sonnet-4-6
    SONNET_IN_PER_1M_USD  = 3.00           # claude-sonnet-4-6 input
    SONNET_OUT_PER_1M_USD = 15.00          # claude-sonnet-4-6 output

    def _row_cost_usd(r):
        """Compute USD cost for a single usage row using the correct model pricing."""
        if r.call_type == 'photo':
            # Vision + Opus pricing
            return (r.input_tokens  / 1_000_000) * OPUS_IN_PER_1M_USD  + \
                   (r.output_tokens / 1_000_000) * OPUS_OUT_PER_1M_USD
        elif r.call_type == 'pdf_import':
            # Sonnet pricing (PDF extraction + AI redistribution)
            return (r.input_tokens  / 1_000_000) * SONNET_IN_PER_1M_USD + \
                   (r.output_tokens / 1_000_000) * SONNET_OUT_PER_1M_USD
        else:
            # Whisper + Haiku pricing (item / room / full)
            whisper = (r.audio_seconds / 60) * WHISPER_PER_MIN_USD
            claude  = (r.input_tokens  / 1_000_000) * HAIKU_IN_PER_1M_USD + \
                      (r.output_tokens / 1_000_000) * HAIKU_OUT_PER_1M_USD
            return whisper + claude

    # ── Overall summary ────────────────────────────────────────────────────
    item_count  = sum(1 for r in rows if r.call_type == 'item')
    room_count  = sum(1 for r in rows if r.call_type == 'room')
    full_count  = sum(1 for r in rows if r.call_type == 'full')
    photo_count = sum(1 for r in rows if r.call_type == 'photo')
    pdf_count   = sum(1 for r in rows if r.call_type == 'pdf_import')

    trans_rows = [r for r in rows if r.call_type in ('item', 'room', 'full')]
    photo_rows = [r for r in rows if r.call_type == 'photo']
    pdf_rows   = [r for r in rows if r.call_type == 'pdf_import']

    total_audio_secs = sum(r.audio_seconds for r in trans_rows)

    whisper_usd     = sum((r.audio_seconds / 60) * WHISPER_PER_MIN_USD for r in trans_rows)
    haiku_usd       = sum((r.input_tokens / 1_000_000) * HAIKU_IN_PER_1M_USD +
                          (r.output_tokens / 1_000_000) * HAIKU_OUT_PER_1M_USD
                          for r in trans_rows)
    photo_opus_usd  = sum((r.input_tokens / 1_000_000) * OPUS_IN_PER_1M_USD +
                          (r.output_tokens / 1_000_000) * OPUS_OUT_PER_1M_USD
                          for r in photo_rows)
    pdf_sonnet_usd  = sum((r.input_tokens / 1_000_000) * SONNET_IN_PER_1M_USD +
                          (r.output_tokens / 1_000_000) * SONNET_OUT_PER_1M_USD
                          for r in pdf_rows)
    total_usd = whisper_usd + haiku_usd + photo_opus_usd + pdf_sonnet_usd

    # ── Group by inspection ────────────────────────────────────────────────
    from collections import defaultdict
    by_insp = defaultdict(lambda: {
        'trans_seconds': 0.0,
        'trans_in': 0, 'trans_out': 0,
        'photo_in': 0, 'photo_out': 0,
        'pdf_in':   0, 'pdf_out':   0,
        'item_calls': 0, 'room_calls': 0, 'photo_calls': 0, 'pdf_calls': 0,
        'latest_at': None,
    })

    for r in rows:
        key = r.inspection_id
        g   = by_insp[key]
        if r.call_type in ('item', 'room', 'full'):
            g['trans_seconds'] += r.audio_seconds
            g['trans_in']      += r.input_tokens
            g['trans_out']     += r.output_tokens
            if r.call_type == 'item':
                g['item_calls'] += 1
            else:
                g['room_calls'] += 1
        elif r.call_type == 'photo':
            g['photo_in']    += r.input_tokens
            g['photo_out']   += r.output_tokens
            g['photo_calls'] += 1
        elif r.call_type == 'pdf_import':
            g['pdf_in']    += r.input_tokens
            g['pdf_out']   += r.output_tokens
            g['pdf_calls'] += 1
        if g['latest_at'] is None or r.created_at > g['latest_at']:
            g['latest_at'] = r.created_at

    # Fetch inspection details for known IDs
    known_ids = [k for k in by_insp if k is not None]
    insp_meta = {}   # id → {address, type, reference}
    if known_ids:
        insp_objs = Inspection.query.filter(Inspection.id.in_(known_ids)).all()
        for insp in insp_objs:
            addr = (insp.property.address if insp.property else None) or f'Inspection #{insp.id}'
            insp_meta[insp.id] = {
                'address':    addr,
                'type':       (insp.inspection_type or '').replace('_', ' ').title(),
                'reference':  insp.reference_number or '',
            }

    inspections_list = []
    for insp_id, g in sorted(by_insp.items(),
                              key=lambda x: x[1]['latest_at'] or datetime.min,
                              reverse=True):
        w_usd  = (g['trans_seconds'] / 60) * WHISPER_PER_MIN_USD
        hk_usd = (g['trans_in']  / 1_000_000) * HAIKU_IN_PER_1M_USD + \
                 (g['trans_out'] / 1_000_000) * HAIKU_OUT_PER_1M_USD
        op_usd = (g['photo_in']  / 1_000_000) * OPUS_IN_PER_1M_USD  + \
                 (g['photo_out'] / 1_000_000) * OPUS_OUT_PER_1M_USD
        pd_usd = (g['pdf_in']    / 1_000_000) * SONNET_IN_PER_1M_USD + \
                 (g['pdf_out']   / 1_000_000) * SONNET_OUT_PER_1M_USD

        meta = insp_meta.get(insp_id, {}) if insp_id else {}

        inspections_list.append({
            'inspection_id':          insp_id,
            'property_address':       meta.get('address', 'Unknown property') if insp_id else 'Unlinked calls',
            'inspection_type':        meta.get('type', ''),
            'reference_number':       meta.get('reference', ''),
            'total_cost_gbp':         round((w_usd + hk_usd + op_usd + pd_usd) * USD_TO_GBP, 4),
            'whisper_cost_gbp':       round(w_usd  * USD_TO_GBP, 4),
            'claude_cost_gbp':        round(hk_usd * USD_TO_GBP, 4),
            'photo_cost_gbp':         round(op_usd * USD_TO_GBP, 4),
            'pdf_import_cost_gbp':    round(pd_usd * USD_TO_GBP, 4),
            'transcription_cost_gbp': round((w_usd + hk_usd) * USD_TO_GBP, 4),
            'item_calls':             g['item_calls'],
            'room_calls':             g['room_calls'],
            'photo_calls':            g['photo_calls'],
            'pdf_calls':              g['pdf_calls'],
            'pdf_tokens':             g['pdf_in'] + g['pdf_out'],
            'audio_minutes':          round(g['trans_seconds'] / 60, 1),
            'latest_at':              g['latest_at'].isoformat() if g['latest_at'] else None,
        })

    # Sort most recent first
    inspections_list.sort(key=lambda x: x['latest_at'] or '', reverse=True)

    # PDF import: distinct inspections + average cost per import, for the
    # per-inspection estimate shown in Settings > Transcription.
    pdf_insp_ids = {r.inspection_id for r in pdf_rows}
    pdf_import_inspections = len(pdf_insp_ids)
    pdf_avg_usd = (pdf_sonnet_usd / pdf_import_inspections) if pdf_import_inspections else 0

    return jsonify({
        'period_days':      int(period),
        'item_calls':       item_count,
        'room_calls':       room_count,
        'full_calls':       full_count,
        'photo_calls':      photo_count,
        'pdf_import_calls': pdf_count,
        'pdf_import_inspections': pdf_import_inspections,
        'total_calls':      len(rows),
        'audio_minutes':    round(total_audio_secs / 60, 1),
        'whisper_cost_gbp': round(whisper_usd   * USD_TO_GBP, 4),
        'claude_cost_gbp':  round(haiku_usd     * USD_TO_GBP, 4),
        'photo_cost_gbp':   round(photo_opus_usd * USD_TO_GBP, 4),
        'pdf_cost_gbp':     round(pdf_sonnet_usd * USD_TO_GBP, 4),
        'pdf_avg_cost_gbp': round(pdf_avg_usd    * USD_TO_GBP, 4),
        'total_cost_gbp':   round(total_usd     * USD_TO_GBP, 4),
        'inspections':      inspections_list,
    })


# ── Deterministic fill guards ─────────────────────────────────────────────────
# The prompts instruct Claude to skip already-transcribed items and never to
# duplicate content — but prompt compliance is advisory. These pure helpers
# enforce the same rules deterministically on the model's output, so a prompt
# slip can't double up field content on the device.

def _norm_fill_line(s: str) -> str:
    return ' '.join((s or '').strip().lower().rstrip('.').split())


def _enforce_processed_skip(filled: dict, processed_ids: list) -> dict:
    """
    Drop any already-transcribed item that Claude re-emitted WITHOUT an explicit
    amendment marker (_descAction / _condAction / _subs / _delete). Hard-enforces
    the prompt's "skip unless explicitly amended" rule.
    """
    if not processed_ids or not isinstance(filled, dict):
        return filled
    processed = {str(pid) for pid in processed_ids}
    out = {}
    for item_id, fields in filled.items():
        if (str(item_id) in processed
                and isinstance(fields, dict)
                and not fields.get('_descAction')
                and not fields.get('_condAction')
                and not fields.get('_subs')
                and not fields.get('_delete')):
            print(f'[transcribe/room] dropped re-emitted already-transcribed item {item_id}')
            continue
        out[item_id] = fields
    return out


def _dedupe_filled(filled: dict) -> dict:
    """
    Remove duplicated content within a room-fill result:
      - repeated lines within description / condition / checkOutCondition
        (clip overlap or the clerk repeating themselves)
      - description lines repeated verbatim in the same item's condition
        (condition wins — "each piece of content appears in ONE field only")
      - duplicate newly-created _subs entries, or a sub identical to the main
        item (check-out subs targeting an existing _sid are never dropped)
    """
    if not isinstance(filled, dict):
        return filled

    def dedupe_lines(text):
        seen, lines = set(), []
        for line in text.split('\n'):
            n = _norm_fill_line(line)
            if n and n in seen:
                continue
            if n:
                seen.add(n)
            lines.append(line)
        return '\n'.join(lines)

    out = {}
    for item_id, fields in filled.items():
        if not isinstance(fields, dict):
            out[item_id] = fields
            continue
        f = dict(fields)
        for key in ('description', 'condition', 'checkOutCondition'):
            if isinstance(f.get(key), str) and f[key]:
                f[key] = dedupe_lines(f[key])

        # Same line in both fields → keep it in condition only
        if isinstance(f.get('description'), str) and isinstance(f.get('condition'), str) and f['condition']:
            cond_lines = {_norm_fill_line(l) for l in f['condition'].split('\n') if _norm_fill_line(l)}
            kept = [l for l in f['description'].split('\n') if _norm_fill_line(l) not in cond_lines]
            f['description'] = '\n'.join(kept)

        if isinstance(f.get('_subs'), list):
            main_key  = (_norm_fill_line(f.get('description') or ''), _norm_fill_line(f.get('condition') or ''))
            seen_subs = {main_key}
            uniq = []
            for sub in f['_subs']:
                if not isinstance(sub, dict):
                    continue
                for k in ('description', 'condition', 'checkOutCondition'):
                    if isinstance(sub.get(k), str) and sub[k]:
                        sub = {**sub, k: dedupe_lines(sub[k])}
                if not sub.get('_sid'):
                    desc_n = _norm_fill_line(sub.get('description') or '')
                    cond_n = _norm_fill_line(sub.get('condition') or sub.get('checkOutCondition') or '')
                    # Phantom sub-item — the model opened a new element but never actually
                    # gave it content (e.g. a dropped self-correction). Never surface a blank
                    # sub-item in the report; drop it rather than passing it through.
                    if not desc_n and not cond_n:
                        continue
                    sub_key = (desc_n, cond_n)
                    if sub_key in seen_subs:
                        continue
                    seen_subs.add(sub_key)
                uniq.append(sub)
            f['_subs'] = uniq
        out[item_id] = f
    return out


def _dedupe_redirect_leaks(filled: dict) -> dict:
    """
    Cross-item safety net for "Return to [item], add to condition/description, ..." commands.
    _dedupe_filled only dedupes lines *within* one item, but a redirect names a different item
    as its target — so when the model both (a) correctly appends/overwrites text on the named
    target item AND (b) leaves a copy of that same text on the item/sub-item that was open right
    before the redirect fired, _dedupe_filled never sees the two copies together to catch it.

    Any line long enough to be a specific observation (short generic phrases like "In good
    order" are excluded) that appears on a _descAction/_condAction target is treated as
    redirected text and stripped from every other item/sub-item in this same batch.
    """
    if not isinstance(filled, dict):
        return filled

    redirected = set()
    for fields in filled.values():
        if not isinstance(fields, dict):
            continue
        for key, action_key in (('description', '_descAction'), ('condition', '_condAction')):
            if fields.get(action_key) and isinstance(fields.get(key), str):
                for line in fields[key].split('\n'):
                    n = _norm_fill_line(line)
                    if n and len(n) > 20:
                        redirected.add(n)

    if not redirected:
        return filled

    def strip(text, is_target):
        if is_target or not isinstance(text, str) or not text:
            return text
        kept = [l for l in text.split('\n') if _norm_fill_line(l) not in redirected]
        return '\n'.join(kept)

    out = {}
    for item_id, fields in filled.items():
        if not isinstance(fields, dict):
            out[item_id] = fields
            continue
        f = dict(fields)
        f['description'] = strip(f.get('description'), bool(f.get('_descAction')))
        f['condition']   = strip(f.get('condition'),    bool(f.get('_condAction')))
        if isinstance(f.get('_subs'), list):
            new_subs = []
            for sub in f['_subs']:
                if not isinstance(sub, dict):
                    new_subs.append(sub)
                    continue
                s = dict(sub)
                s['description'] = strip(s.get('description'), False)
                s['condition']   = strip(s.get('condition'), False)
                new_subs.append(s)
            f['_subs'] = new_subs
        out[item_id] = f
    return out


_SUBITEM_TRIGGER_RE = _re.compile(
    r'\badd\s+(?:a\s+)?sub[\s-]?items?\b|\b(?:next\s+)?sub[\s-]?item\b', _re.IGNORECASE
)


def _count_subitem_triggers(transcript: str) -> int:
    """Counts explicit 'add sub item' / 'sub-item' style trigger phrases in a transcript."""
    return len(_SUBITEM_TRIGGER_RE.findall(transcript or ''))


def _count_subs_emitted(filled: dict) -> int:
    """Counts total _subs entries across every item in a room-fill result."""
    if not isinstance(filled, dict):
        return 0
    return sum(
        len(fields['_subs'])
        for fields in filled.values()
        if isinstance(fields, dict) and isinstance(fields.get('_subs'), list)
    )


def _subitem_retry_note(trigger_count: int, sub_count: int) -> str:
    """
    Prompt addendum used when a first pass under-produced sub-items relative to the number
    of explicit trigger phrases in the transcript (see EXPLICIT SUB-ITEM TRIGGER rule).
    """
    return (
        f'\n══════════════════════════════════════════════════════\n'
        f'RETRY — you missed a sub-item last time\n'
        f'══════════════════════════════════════════════════════\n'
        f'Your previous pass over this exact transcript produced only {sub_count} sub-item(s), but the\n'
        f'transcript contains {trigger_count} explicit sub-item trigger phrase(s) ("add sub item",\n'
        f'"sub-item", etc). That means at least one trigger was dropped or merged back into a main\n'
        f'item instead of becoming its own _subs entry. Re-parse the transcript from scratch, find\n'
        f'every occurrence of a trigger phrase, and confirm each one produces its own _subs entry —\n'
        f'do not let a long run of prior content, or a repeated condition phrase, cause you to skip one.\n'
    )


def _name_variants(name: str) -> set:
    """Singular/plural variants of an item name, lowercased, for loose substring matching."""
    n = (name or '').strip().lower()
    if not n:
        return set()
    return {n, (n[:-1] if n.endswith('s') else n + 's')}


def _find_missing_mentioned_items(transcript: str, items: list, filled: dict) -> list:
    """
    Finds template items whose exact name is clearly spoken somewhere in the transcript
    (as a substring, singular or plural) but which never appear as a key in `filled` AT ALL —
    not even a "_delete" entry. This is a strong signal the model heard the heading but
    swallowed its content into whichever item was already open, instead of switching to a
    new chapter — the failure mode behind a "Contents" (or similar) section going missing
    entirely, with its items wrongly attached as sub-items of the previous item.
    """
    t = (transcript or '').lower()
    if not t:
        return []
    filled_keys = {str(k) for k in (filled or {}).keys()}
    missing = []
    for item in items:
        item_id = str(item.get('id'))
        if item_id in filled_keys:
            continue
        name = item.get('name') or ''
        if any(v and v in t for v in _name_variants(name)):
            missing.append(item)
    return missing


def _missing_item_retry_note(missing_items: list) -> str:
    """Prompt addendum used when a template item was clearly mentioned but never output at all."""
    names = ', '.join(f'"{i.get("name")}"' for i in missing_items)
    return (
        f'\n══════════════════════════════════════════════════════\n'
        f'RETRY — an item was mentioned but never appeared in your output\n'
        f'══════════════════════════════════════════════════════\n'
        f'The clerk\'s transcript clearly contains the name of the following item(s), but your\n'
        f'previous pass produced NO entry for them at all — not even a "_delete": {names}.\n'
        f'This almost always means the heading announcement was missed and its content got\n'
        f'wrongly attached to whatever item was already open, instead of switching to a new\n'
        f'chapter. Re-parse the transcript, find where each of these item names is announced,\n'
        f'and give each one its own top-level entry in your JSON output with whatever content\n'
        f'follows it — do not leave it merged into the item that came before it.\n'
    )


def _fill_room_with_subitem_retry(fill_fn, full_transcript, section_name, items, processed_item_ids, fn_name):
    """
    Calls fill_fn (either _claude_fill_room or _claude_fill_room_damage), then checks for two
    known LLM compliance slips: (1) fewer _subs produced than explicit "add sub item" triggers
    in the transcript, and (2) a template item whose name is clearly spoken but never appears
    in the output at all (usually because its content got swallowed into the previous item's
    sub-item chain — e.g. a "Contents" section vanishing entirely). Prompt reinforcement alone
    can't guarantee either won't happen, so when either is detected this retries ONCE with a
    pointed correction — a genuine second chance, bounded to a single extra call.
    """
    filled, fill_msg = fill_fn(full_transcript, section_name, items, processed_item_ids or None)
    filled = _enforce_processed_skip(filled, processed_item_ids)

    trigger_count = _count_subitem_triggers(full_transcript)
    sub_count     = _count_subs_emitted(filled)
    sub_shortfall = bool(trigger_count and sub_count < trigger_count)
    missing_items = _find_missing_mentioned_items(full_transcript, items, filled)

    if sub_shortfall or missing_items:
        notes = []
        if sub_shortfall:
            print(f'[{fn_name}] sub-item mismatch in "{section_name}": '
                  f'{trigger_count} trigger(s), {sub_count} sub(s) emitted')
            notes.append(_subitem_retry_note(trigger_count, sub_count))
        if missing_items:
            names = ', '.join(i.get('name', '?') for i in missing_items)
            print(f'[{fn_name}] item(s) mentioned but never output in "{section_name}": {names}')
            notes.append(_missing_item_retry_note(missing_items))

        retry_note = ''.join(notes)
        retried, retry_msg = fill_fn(full_transcript, section_name, items, processed_item_ids or None, retry_note=retry_note)
        retried = _enforce_processed_skip(retried, processed_item_ids)

        retry_sub_count = _count_subs_emitted(retried)
        retry_missing   = _find_missing_mentioned_items(full_transcript, items, retried)
        improved = retry_sub_count > sub_count or len(retry_missing) < len(missing_items)
        if improved:
            print(f'[{fn_name}] retry improved: subs {sub_count}→{retry_sub_count}, '
                  f'missing {len(missing_items)}→{len(retry_missing)}')
            filled, fill_msg = retried, retry_msg
        else:
            print(f'[{fn_name}] retry did not improve — keeping original')
    return filled, fill_msg


def _claude_fill_room(transcript: str, section_name: str, items: list, processed_ids: list = None, retry_note: str = '') -> dict:
    """
    Fill a single room's items from a continuous dictation transcript.
    Item names are used as 'chapter headings' — the clerk says the item name
    then describes it, so the AI maps each passage to the correct item.

    items: [{ 'id': str, 'name': str, 'hasCondition': bool, 'hasDescription': bool }]
    processed_ids: item IDs already filled in a previous pass — skip unless explicitly amended.
    retry_note: appended to the prompt when re-attempting after a detected sub-item mismatch.

    Returns: { itemId: { 'description': '...', 'condition': '...' } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  {i+1}. ID: "{item["id"]}", Name: "{item["name"]}"'
        for i, item in enumerate(items)
    )

    processed_note = ''
    if processed_ids:
        id_list = ', '.join(f'"{pid}"' for pid in processed_ids)
        processed_note = f"""
══════════════════════════════════════════════════════
ALREADY-TRANSCRIBED ITEMS — skip unless explicitly amended
══════════════════════════════════════════════════════
The following item IDs were filled in a previous transcription pass and already have content:
  {id_list}

RULE: Omit these items from your output entirely UNLESS the clerk explicitly amends, adds to,
creates a sub-item on, or deletes them. If a chapter heading matches an already-transcribed
item but the content that follows is a plain description or condition (no command word) — skip it.

Include an already-transcribed item ONLY when the clerk uses one of these patterns:

  OVERWRITE — set _descAction and/or _condAction = "overwrite":
    "Amend [item name] [content]"
    "Amend [item name] description [content]"
    "Amend [item name] condition [content]"
    "[item name]. Amend. [content]"
    "[item name]. Amend description. [content]"
    "[item name]. Amend condition. [content]"
    "Return to [item name], amend, [content]"
    "Return to [item name], amend description, [content]"
    "Return to [item name], amend condition, [content]"

  APPEND — set _descAction and/or _condAction = "append":
    "Add to [item name] [content]"
    "Add to [item name] description [content]"
    "Add to [item name] condition [content]"
    "[item name]. Add. [content]"
    "[item name]. Add to description. [content]"
    "[item name]. Add to condition. [content]"
    "Return to [item name], add, [content]"
    "Return to [item name], add to description, [content]"
    "Return to [item name], add to condition, [content]"

  SUB-ITEM — output only _subs, no _descAction/_condAction:
    "[item name]. Sub-item. [description and condition]"
    "[item name]. Add sub item. [description and condition]"
    "Return to [item name], add sub item, [description and condition]"

  DELETE — output only _delete: true:
    "[item name]. Delete item."
    "[item name]. Not Applicable."
    "[item name]. Not seen."  (only when immediately after item name, not within a description)

CHAPTER-HEADING AMENDMENT PATTERN — critical rule:
When the clerk names an already-transcribed item as a CHAPTER HEADING and then IMMEDIATELY
uses an amendment or sub-item command word ("Amend", "Add", "Sub-item"), treat this as an
explicit amendment even if the item name is not repeated after the command word.
  Example: "Ceiling. Amend condition. Light scratching to left wall."
    → {{"<ceilingId>": {{"condition": "Light scratching to left wall", "_condAction": "overwrite"}}}}
  Example: "Door and frame. Add sub item. White painted frame, light scuffing."
    → {{"<doorId>": {{"_subs": [{{"description": "White painted frame", "condition": "Light scuffing"}}]}}}}
  Example: "Walls. Add to condition. Some discolouration to right wall."
    → {{"<wallsId>": {{"condition": "Some discolouration to right wall", "_condAction": "append"}}}}
"""

    prompt = f"""You are processing a UK property inventory inspection dictation for a single room.

PHASE 1 — INTERNALIZE THE TEMPLATE
Before reading the transcript, memorize the following item sequence for this room.
These are the ONLY items you will fill. They are numbered in the order the clerk is expected to cover them.

Room: {section_name}

ROOM ITEMS IN ORDER:
{items_list}

PHASE 2 — PARSE THE TRANSCRIPT
The clerk walked through the room and spoke each item name aloud followed by its description and condition.
Item names act as CHAPTER HEADINGS. When the clerk says an item name as a standalone phrase that
EXACTLY matches a name from the list above, everything that follows belongs to that item until
the next exact item name is spoken as a standalone heading.

CHAPTER HEADING MATCHING RULES:
A chapter heading is ONLY when the clerk speaks an item reference BY ITSELF — standalone,
with no preceding adjectives, descriptive words, prepositions, or qualifiers.
Case-insensitive; "&" and "and" are interchangeable; hyphens are optional.

TWO TIERS OF MATCHING — apply in order:

TIER 1 — EXACT MATCH (preferred):
The spoken phrase matches the full item name from the list.
  ✓ "Flooring" → triggers "Flooring"
  ✓ "Built-in storage" → triggers "Built-In Storage"
  ✓ "Kitchen base units" → triggers "Kitchen Base Units"

SINGULAR/PLURAL OF THE SAME WORD also counts as Tier 1 — this is NOT the same thing as a
partial word or a different word. Only apply this when the spoken word and the item-name word
share the same root and differ ONLY by a trailing "s":
  ✓ "Content" → triggers "Contents" (same root word, singular spoken form)
  ✓ "Curtain" → triggers "Curtains & Blinds" (same root word "curtain")
  ✗ "Floor" does NOT trigger "Flooring" — different word, not a singular/plural pair
  ✗ "Door" does NOT trigger "Door & Frame" — that is a partial-word case, covered by Tier 2 rules below, not this one

KNOWN WHISPER MISHEARING also counts as Tier 1 — Whisper frequently mis-transcribes "ceiling"
as the homophone "sealing" (identical pronunciation). Treat "sealing" spoken as a standalone
heading exactly as if the clerk had said "Ceiling":
  ✓ "Sealing" → triggers "Ceiling"
  ✓ "Return to sealing, add to condition, ..." → triggers "Ceiling" via the amendment rules below

TIER 2 — UNIQUE PARTIAL MATCH (fallback when no exact match):
The spoken phrase is a distinctive word or phrase that appears in exactly ONE item name in
the list AND does not appear in any other item name. Use this to handle natural abbreviations.
  ✓ "Base units" → triggers "Kitchen Base Units" (only item containing "base units")
  ✓ "Wall units" → triggers "Kitchen Wall Units" (only item containing "wall units")
  ✓ "Extractor" → triggers "Extractor Fan" (only item containing "extractor")
  ✓ "Sockets" → triggers "Switches & Sockets" (only item containing "sockets")
  ✗ "Units" → does NOT match — "units" appears in both "Kitchen Base Units" and "Kitchen Wall Units" — ambiguous
  ✗ "Door" → does NOT match "Door & Frame" if there is also an "Internal Door" item — ambiguous

SAFETY RULE: if the spoken phrase could match more than one item name, do NOT use Tier 2.
Leave the content with the current item rather than routing it to an ambiguous heading.

UNRECOGNISED HEADINGS — CRITICAL RULE:
If the clerk announces a standalone name that does NOT match any item (by Tier 1 or Tier 2),
you MUST ignore it completely — do not route its content to any other item.
The clerk may have deleted an item before recording and then mentioned it out of habit.
When this happens:
  - Skip the unrecognised name and everything the clerk says about it, up to the next
    recognised chapter heading.
  - Do NOT attach that skipped content to the item that was open before the unrecognised heading.
  - Do NOT include the unrecognised item in your output at all.

  ✗ "white painted ceiling" → does NOT trigger "Ceiling" — words before the noun
  ✗ "light wood flooring" → does NOT trigger "Flooring" — words before the noun
  ✗ "frosted glass light fitting" → does NOT trigger "Lighting" — descriptive phrase
  ✗ "heavy scratches to flooring" → does NOT trigger "Flooring" — prepositional phrase

DO NOT ROUTE BY CONTENT SEMANTICS — this rule overrides your default understanding:
You are NOT permitted to look at what content describes and use that to decide which item it
belongs to. Your ONLY routing mechanism is an exact standalone item name announcement.

  Even if "white painted ceiling" obviously describes a ceiling surface, and even if "Ceiling"
  exists as an item in the template — if the clerk did not say "Ceiling" alone as a standalone
  announcement, the content STAYS IN THE CURRENT ITEM. Do not move it.

  Even if "frosted glass light fitting" describes a light fitting, and "Lighting" is an item —
  if no standalone "Lighting" announcement was made, the content STAYS IN THE CURRENT ITEM.

  Your semantic understanding of what words describe MUST NOT influence routing decisions.
  Only explicit standalone announcements route content.

CURRENT-ITEM LOCK — this rule overrides everything else:
Once inside an item, every word belongs to that item until an exact standalone item name is
announced. This is absolute. There are no exceptions for content that sounds like it belongs
to another item.

CRITICAL EXAMPLE — showing correct versus wrong behaviour for a real transcript:

Transcript:
"built-in storage, white painted wooden door, white painted frame, chrome handles,
white painted ceiling, frosted glass light fitting, white painted walls, white plastic
switches and sockets, white painted woodwork, light wood flooring, in good order,
light scratches to flooring, right hand side on entry"

CORRECT — everything after "built-in storage" stays in Built-in Storage:
  Built-in Storage
    Description: White painted wooden door / White painted frame / Chrome handles /
                 White painted ceiling / Frosted glass light fitting / White painted walls /
                 White plastic switches and sockets / White painted woodwork / Light wood flooring
    Condition:   In good order / Light scratches to flooring, right hand side on entry

WRONG — do NOT do this:
  Built-in Storage: door, frame, handles only
  Ceiling: white painted  ← clerk never said "Ceiling" alone
  Lighting: frosted glass light fitting  ← clerk never said "Lighting" alone
  Walls: white painted  ← clerk never said "Walls" alone
  Flooring: light wood flooring  ← clerk never said "Flooring" alone

The clerk described the interior of the Built-in Storage unit (its ceiling, light fitting, walls,
woodwork, and flooring). None of these are standalone item announcements — they are all content
of the Built-in Storage item until the clerk explicitly announces a new item name alone.
{processed_note}
Transcript:
"{transcript}"

RULES:
1. A chapter heading MUST exactly match the full item name from the numbered list above (case-insensitive;
   "&" and "and" are interchangeable). Partial words and abbreviations are NEVER chapter headings.
   Examples: "Floor" ≠ "Flooring". "Door" ≠ "Door & Frame". "Storage" ≠ "Built-In Storage".
   The clerk must say the complete item name for a heading switch to occur.
2. Extract description and condition separately. If the clerk says a single phrase, put it in description.
3. CRITICAL: Use the EXACT words the clerk spoke. Do not rephrase, paraphrase, or substitute synonyms.
   - "good order" → "Good order" (NOT "Good condition")
   - "fair wear and tear" → "Fair wear and tear"
   - "as new" or "as inventory" → preserve exactly
4. ONLY remove filler sounds (um, uh, er, errr, umm, erm) and clear false starts where the clerk immediately restarts the same phrase (e.g. "white — white painted door" → "white painted door"). Do NOT remove, shorten, or paraphrase any actual content — reproduce the clerk's words in full.
   SELF-CORRECTION: if the clerk says "sorry" OR "correction" mid-dictation, treat it as retracting
   everything said for the CURRENT element since the last chapter heading or sub-item trigger — not
   just the single word or phrase immediately before it. Discard that retracted content entirely and
   continue from what follows the correction word.
   e.g. "in good order, and sorry, and one chrome rail, tarnished" → discard "in good order"; output "1 x chrome rail" (description) + "Tarnished" (condition).
   e.g. "Built-in storage, mirrored medicine cabinet, correction, none seen" → the correction retracts
   "mirrored medicine cabinet" entirely, leaving nothing said for Built-in Storage except "none seen".
   Treat this exactly as if the clerk had said "Built-in storage, none seen" from the start — apply the
   "not seen" deletion rule below. Do NOT create an item, sub-item, or any field content from the
   retracted material, and do NOT leave a sub-item with no description or condition.
5. Only fill items that are mentioned. Omit unmentioned items entirely from the output.
6. {_UK_SPELLING_RULE}
7. If only one piece of information is given for an item, put it in description.
8. REPEATED OR OVERLAPPING CONTENT — treat duplicates as ONE:
   The transcript is stitched together from several audio clips and may contain the same
   passage twice — overlapping recordings, restarted sentences, or the clerk repeating
   themselves. If the same or nearly the same wording appears more than once for an item,
   use it ONCE only. Never output the same observation twice in any field, and never
   create a duplicate sub-item from repeated speech.
   A repeated plain mention of an already-covered item is NEVER an amendment or an append —
   only the explicit command words ("Amend", "Add to", "Sub-item", "Delete item",
   "Not Applicable") make it one.
   EXCEPTION — this dedup rule NEVER suppresses an explicit sub-item trigger. If the clerk
   says "sub-item" / "add sub item" and the content that follows happens to reuse the exact
   same condition wording as the main item or an earlier sub-item (e.g. two elements both
   ending "tested for power"), that is NOT a repeated/stitched passage — it is the clerk
   independently giving the same verdict for a second, genuinely different component. Create
   the sub-item regardless of wording overlap. Only collapse content when there was NO
   explicit trigger and the wording is a stitching artefact.

FORMATTING NUMBERS AND QUANTITIES:
- Convert spoken numbers to numerals: "two" → "2", "three" → "3"
- Format quantities as "N x item": "two green curtains" → "2 x green curtains"

NUMBER HOMOPHONES — Whisper frequently mishears spoken numbers as similar-sounding words.
Apply the following substitutions when the context matches:

  "for [noun]"  → "4 x [noun]"   e.g. "for rawl plug holes" → "4 x rawl plug holes"
  "to [noun]"   → "2 x [noun]"   e.g. "to scratches to low level" → "2 x scratches to low level"
  "won [noun]"  → "1 x [noun]"   e.g. "won crack" → "1 x crack"

HOW TO DECIDE: "to" is a NUMBER when ALL of these are true:
  1. It is the FIRST word of the clause — either the very first word spoken for that element,
     or the first word after a comma separating components.
  2. It is followed DIRECTLY by a countable noun or plural noun with NO article (no "the", "a", "an").
  3. It is NOT preceded by a defect/condition word in the same clause.

"to" is a PREPOSITION (leave unchanged) when ANY of these are true:
  ✗ It follows a defect or condition word:
      "scratches to low level", "scuffing to base", "chips to door", "crack to frame"
      → here "to" is a location preposition showing WHERE the defect is
  ✗ It follows a command word:
      "return to [item]", "add to condition", "tested for power"
  ✗ It is followed by "the", "a", "an", or a location word:
      "to the left", "to base", "to centre", "to right hand side"

DISTINGUISHING PATTERN — "to [noun] to [location]":
  When you see "to" followed by a noun, then another "to" followed by a location,
  the FIRST "to" is the number and the SECOND "to" is the location preposition:
    "to scratches to low level"  → "2 x scratches to low level"
    "to cracks to top edge"      → "2 x cracks to top edge"
    "to hooks to door"           → "2 x hooks to door"

  ✓ "to scratches to low level"   → first "to" = two (precedes countable noun "scratches")
  ✓ "for rawl plug holes"         → "for" = four (precedes countable noun at start of element)
  ✓ "to hooks"                    → "to" = two (first word, countable plural, no article)
  ✗ "scuffing to base"            → preposition (follows defect word "scuffing")
  ✗ "return to walls"             → command preposition
- Capitalise the first word of each line
- Do NOT use bullet points or dashes
- {_multi_component_rule("a description or condition")}

{_APPLIANCE_FORMATTING_RULE}

SPLITTING description vs condition:
- A CONDITION SIGNAL is ANY of the following:
    (a) A state-grade phrase: "in good order", "in fair order", "in poor order", "good order",
        "fair order", "poor order", "as new", "as inventory", "in good condition"
    (b) ANY word or phrase listed in the CONDITION VOCABULARY block above — this includes
        defect words (chipping, cracked, marks, rust, mould…), surface observations (seam,
        gapping, swelling…), fixings/alterations (nail, nails, screw, hook, cabling…),
        and functional observations (tested, working, not working…)
    (c) A functional observation ("appear complete", "tested", "appears working")
- Everything said AFTER a condition signal is also condition
- If no condition is mentioned, default condition to "In good order"
- DESCRIPTION CLOSES PERMANENTLY the moment ANY condition signal is encountered.
  Once closed, NO further text may be added to description — not even text that sounds
  descriptive. All remaining text for that element goes into condition only.
  The only exception is an explicit amendment command from the clerk.
- NEVER write a condition signal word in the description field. This applies equally to
  classic defect words AND to fixings/alterations AND to surface observations. Examples:
    "white painted wooden door, odd chipping to base, light scuff marks"
    → description: "White painted wooden door"
    → condition:   "Odd chipping to base\nLight scuff marks"

    "white painted walls, 2 x nails fitted to high level near wall"
    → description: "White painted"
    → condition:   "2 x nails fitted to high level near wall"

    "white painted skirting, cabling attached"
    → description: "White painted skirting"
    → condition:   "Cabling attached"
  Do NOT put condition content in both fields. Each piece of content appears in ONE field only.
  NEVER output the same sentence, phrase, or observation in both description and condition.
  If you are unsure which field a phrase belongs to, put it in condition ONLY.

HOW TO PARSE EACH ITEM — follow this algorithm exactly:

STEP 1: When the clerk says an item name (CHAPTER HEADING), start collecting for that item.
STEP 2: Collect words as DESCRIPTION for the current element, until you hit a CONDITION SIGNAL PHRASE.
STEP 3: When you hit a CONDITION SIGNAL PHRASE, it IMMEDIATELY and PERMANENTLY closes the description.
         The description field is now LOCKED — no further text may be written to it for this element
         under any circumstances (unless the clerk explicitly uses an amendment command).
         The condition signal PLUS any location qualifiers that follow ("to [place]", "at [place]",
         "near [place]", "throughout", "on [place]") = the CONDITION for the current element.
         Keep collecting into the condition until you reach a new DESCRIPTIVE TERM or the next chapter heading.
STEP 4: After a condition closes, if the next word is a DESCRIPTIVE TERM (material, colour, surface, quantity),
         it starts a NEW ELEMENT → a "_subs" entry with its own description and condition.
         → Go back to STEP 2 for the new element.
STEP 5: Repeat for as many elements as the clerk describes.

The first element = the main item fields ("description" + "condition").
Each additional element = a "_subs" entry.

CONDITION SIGNAL PHRASES — these close the current element's description:
  State phrases:  "in good order", "in fair order", "in poor order", "good order", "fair order",
                  "poor order", "as new", "as inventory", "in good condition", "in fair condition",
                  "in poor condition", "in clean condition"
  Defect phrases: "light scuffing", "light scratching", "light marking", "light staining",
                  "chipped", "cracked", "stained", "marked", "damaged", "worn", "faded",
                  "scratched", "some wear", "fair wear and tear",
                  "loose", "slightly loose", "tight", "stiff", "sticky", "missing",
                  "broken", "rattling", "squeaking", "bent", "rusted", "corroded",
                  "scuff to", "chip to", "crack to", "stain to", "mark to", "scratch to"

══════════════════════════════════════════════════════
CRITICAL LOCATION QUALIFIER RULE — read this carefully
══════════════════════════════════════════════════════
The words "to [location]", "at [location]", "near [location]", or "on [location]" that
IMMEDIATELY FOLLOW a defect/state phrase are PART OF THE CONDITION.
They tell you WHERE the defect is. They are NEVER the start of a new element.

  ✓ CORRECT: "light scuffing to right hand side wall"
      → condition: "Light scuffing to right hand side wall"
      → "right hand side wall" is the scuffing's location — NOT a new sub-item description.

  ✓ CORRECT: "chip to base of door"
      → condition: "Chip to base of door"

  ✓ CORRECT: "marked to left hand wall"
      → condition: "Marked to left hand wall"

A new element ONLY starts when a NEW DESCRIPTIVE TERM appears (material, colour, surface,
quantity) AFTER the condition has fully closed.

══════════════════════════════════════════════════════
STRICT CHAPTER HEADING RULE — prevents content bleeding between items
══════════════════════════════════════════════════════
A chapter heading switch can ONLY occur when ALL of the following are true:
  1. The previous item's content (description AND condition) has fully closed.
  2. The item name is the VERY FIRST word(s) of a new utterance — nothing spoken before it
     in the same clause, phrase, or breath group.
  3. The spoken phrase EXACTLY matches the full item name from the list (case-insensitive;
     "&" ↔ "and"). Partial words and abbreviations do not qualify.

Words matching another item's name that appear WITHIN an item's description or condition
are NEVER a chapter heading switch — they are content for the CURRENT item only.

  ✓ CORRECT: "Built-in storage. White painted door and frame, in good order."
      → Entirely Built-in storage. "door and frame" is part of the storage description.
        It does NOT switch to the "Door & Frame" item.

  ✓ CORRECT: "Built-in storage. White shelving unit, floor-level drawer, in good order."
      → Entirely Built-in storage. "floor-level" is NOT a heading for Flooring.
        "floor" appears mid-sentence as part of a description — it stays with Built-in storage.

  ✓ CORRECT: "Built-in storage. White painted walls to interior, in good order."
      → Entirely Built-in storage. "walls" here refers to the interior surfaces of the
        storage unit, not the room's Walls item.

  ✗ WRONG: switching to "Flooring" because "floor" appears in "floor-level shelf" inside
      a Built-in Storage passage — this is content bleeding and must never happen.

  ✗ WRONG: treating "door and frame" inside a Built-in Storage passage as a heading for
      the separate "Door & Frame" item — this is content bleeding.

  ✓ CORRECT: "Built-in storage. White painted door and frame, in good order.
              Door and frame. White painted timber door. In good order."
      → The second "Door and frame" opens a CLEARLY ISOLATED new passage after Built-in
        storage's condition has closed — this correctly switches to the Door & Frame item.

The definitive test: does the item name appear as the FIRST WORD(S) after a condition
has fully closed? If yes → chapter heading. If it appears after other words in a running
sentence → it is content, never a heading.

══════════════════════════════════════════════════════
DELETE ITEM — remove command
══════════════════════════════════════════════════════
The clerk may say "[item name] Delete Item", "[item name] Not Applicable", or
"[item name] Not seen" to mark an item as not present in the property.
When you detect any of these commands:
  - Set "_delete": true on that item's output
  - Do NOT fill description or condition — omit them

PARTIAL NAME MATCHING FOR DELETION ONLY:
For deletion commands (not seen / not applicable / delete item), if the clerk speaks a word
that is a unique and distinctive part of an item name — and no other item in the list contains
that word — treat it as a match for that item.
  e.g. "storage, not seen" → matches "Built-in Storage" (the word "storage" is unique to it)
  e.g. "heating, not seen" → matches "Heating" (exact match)
  e.g. "curtains, none seen" → matches "Curtains & Blinds"
This relaxed matching applies ONLY to deletion. Chapter heading switches for content still
require an exact match.

CRITICAL CONTEXT RULE FOR "not seen":
"Not seen" is a delete command ONLY when it appears IMMEDIATELY after an item title with
no intervening description. If it appears inside a longer passage about the item, it is
descriptive content (e.g. referring to a serial number that could not be read) and must
NOT trigger deletion.

EXCEPTION — self-correction retracts the intervening description: if a "sorry"/"correction"
self-correction (see the SELF-CORRECTION rule above) wipes out everything said for the item
since its heading, "not seen" immediately after that correction counts as immediately after
the item title too — delete the item.
  ✓ DELETE: "Built-in storage, mirrored medicine cabinet, correction, none seen."
      → the correction retracts "mirrored medicine cabinet", leaving "none seen" as if it were
        the only thing said → {{"<storageId>": {{"_delete": true}}}}

  ✓ DELETE: "Windows & Frames. Not seen."
      → {{"<windowsId>": {{"_delete": true}}}}
  ✗ NOT DELETE: "BOSCH black glass hob, model and serial number not seen."
      → dictate normally; "not seen" refers to the serial number, not the item

Examples:
  "Built-in Storage. Delete Item."
  → {{"<builtInStorageId>": {{"_delete": true}}}}
  "Fireplace. Not Applicable."
  → {{"<fireplaceId>": {{"_delete": true}}}}
  "Windows & Frames. Not seen."
  → {{"<windowsId>": {{"_delete": true}}}}

══════════════════════════════════════════════════════
EXPLICIT SUB-ITEM TRIGGER — highest priority rule
══════════════════════════════════════════════════════
The clerk may use ANY of the following phrases to EXPLICITLY signal a new sub-item:
  "sub-item", "sub item", "next sub-item", "next sub item",
  "add sub item", "add sub-item", "add a sub item", "add a sub-item"

THIS TRIGGER IS ABSOLUTE AND UNCONDITIONAL — it fires every single time it is spoken, with
NO exceptions, regardless of:
  - How long or short the current item's condition list already is. Even if the main item
    already has five, six, or more condition observations stacked up, "add sub item" still
    immediately closes that list and starts a new element — it never gets lost or ignored
    as "just one more item in the list."
  - Whether the sub-item's own description or condition wording repeats or resembles wording
    already used earlier in the same item (see the dedup exception above) — a repeated
    condition phrase is NOT a reason to skip creating the sub-item.
  - Whether this is the first sub-item trigger in the room or the sixth in a row (e.g. a
    Contents item with many small objects each added via "add sub item") — every occurrence
    creates its own new element with equal priority; a long streak of triggers must not cause
    later ones to be dropped or merged back into the main item.
If you find yourself about to append post-trigger content into the main item's description or
condition field (or drop it there because a run of conditions was already in progress), STOP —
that is always wrong. The content belongs in a new _subs entry.

When you encounter any variation of these phrases:
  - Immediately close the current element (its description + condition are complete)
  - Begin collecting a fresh description and condition for the next _subs entry
  - Do NOT treat the trigger phrase itself as part of any description or item name
  - CRITICAL: everything after the trigger belongs EXCLUSIVELY to the sub-item. Do NOT
    also write it into the main item's description or condition fields. Each piece of
    content appears in exactly ONE place — either the main item or a sub-item, never both.

The "Add sub item" command may appear at any point in the dictation — including at the start
of a new recording clip — to add a sub-item to the most recently described room item.
It may also appear AFTER a fully described item (description + condition already given),
in which case what follows is the new sub-item's content.

CRITICAL — "most recently described room item" ALWAYS means the most recently OPENED CHAPTER
HEADING, and this reassigns every time a new standalone item name is announced — it never
falls back to an earlier item, no matter how many items in the room each have their own
"add sub item" sequence. A room can contain several DIFFERENT items that each use "add sub
item" one after another — every trigger belongs to whichever chapter is CURRENTLY open at the
moment it is spoken, full stop.

  Example — two different items each get their own sub-item sequence in one room:
    "Smoke Alarms. One smoke alarm. Checked with power. Contents. Wall mounted alarm panel.
     In good order. Not tested. Add sub item. White alarm panel with key. In good order.
     Add sub item. White fitted thermostat. In good order."
  → Smoke Alarms: description="1 x smoke alarm"  condition="Checked with power"  (NO subs)
  → Contents:     description="Wall mounted alarm panel"  condition="In good order\nNot tested"
                  sub[0]: description="White alarm panel with key"  condition="In good order"
                  sub[1]: description="White fitted thermostat"     condition="In good order"
  ✗ WRONG: attaching "White alarm panel with key" or "White fitted thermostat" as sub-items of
    Smoke Alarms — the chapter heading "Contents" already switched the active item before either
    trigger was spoken, so both subs belong to Contents, never to the item spoken before it.

Example — two-wall room with explicit trigger:
  "Walls. White emulsion. In good order. Sub-item. Light scuffing to base of wall."
  → main:   description="White emulsion"  condition="In good order"
  → sub[0]: description=""               condition="Light scuffing to base of wall"

Example — LONG condition run before the trigger (do NOT lose the trigger in the list):
  "Walls. Painted white. White scuff marks below left window. Odd scuff marks to left-hand
   wall. Line removal mark right of windows. 2 large shaded sections to facing wall. Odd
   patchy marks around light switches. Plastic fixture next to entry door. Add sub item.
   Part beige tiled. In good order."
  → main:   description="Painted white"
            condition="White scuff marks below left window\nOdd scuff marks to left-hand wall\n
                       Line removal mark right of windows\n2 x large shaded sections to facing wall\n
                       Odd patchy marks around light switches\nPlastic fixture next to entry door"
  → sub[0]: description="Part beige tiled"  condition="In good order"
  ✗ WRONG: appending "Part beige tiled" as a seventh line onto the main item's condition list —
    the six items before the trigger do NOT make the trigger any less binding on item seven.

Example — sub-item condition wording matches the main item's condition wording exactly:
  "Light. Pendant hanging light fixture with white metal shade. Tested for power.
   Add sub item. Plastic domed light fixture. Tested for power."
  → main:   description="Pendant hanging light fixture with white metal shade"  condition="Tested for power"
  → sub[0]: description="Plastic domed light fixture"                          condition="Tested for power"
  ✗ WRONG: merging "Plastic domed light fixture" into the main item's description because its
    condition ("Tested for power") repeats the main item's condition verbatim — the repeated
    wording is a coincidence of two different fittings both being tested and working, not a
    stitched/duplicated recording. The explicit "Add sub item" trigger still applies in full.

Example — door and frame with "Add sub item":
  "Door and frame. White UPVC door, chrome handle. In good order. Add sub item.
   White painted frame, chrome hinges. Light scuffing to base."
  → main:   description="White UPVC door\nChrome handle"     condition="In good order"
  → sub[0]: description="White painted frame\nChrome hinges" condition="Light scuffing to base"

Example — three elements with two triggers:
  "Walls. White emulsion. In good order. Sub-item. White emulsion. Light scuffing to base.
   Sub-item. White emulsion. Fair wear and tear."
  → main:   description="White emulsion"  condition="In good order"
  → sub[0]: description="White emulsion"  condition="Light scuffing to base"
  → sub[1]: description="White emulsion"  condition="Fair wear and tear"

When no explicit trigger is used, fall back to the automatic detection rules below.

══════════════════════════════════════════════════════
THE GOLDEN RULE — what triggers a new sub-item (automatic detection)
══════════════════════════════════════════════════════
A new sub-item is created ONLY when, after a condition closes, the clerk begins describing
a DIFFERENT surface or component with its own descriptive words.

  ✓ Creates sub-item: "Green painted [condition closes] … White painted …"
      (new colour = new element)
  ✓ Creates sub-item: "White UPVC door, in good order … White painted frame, light scuffing"
      (new component = new element)
  ✗ Does NOT create sub-item: "light scuffing to right hand side wall"
      ("right hand side wall" is a location qualifier, not a new component)

MULTI-COMPONENT (no sub-item): When the clerk lists several parts of the SAME thing and
  gives ONE condition phrase at the end covering everything:
  "White painted door, white painted frame, chrome lever handle … in good order"
  → description: "White painted door\nWhite painted frame\nChrome lever handle"
    condition:   "In good order"
  This is NOT a sub-item — everything shares one condition phrase.

WORKED EXAMPLES:

EXAMPLE 1 — Two walls, each with its own condition → main + 1 sub-item:
  Transcript: "Walls. Green painted, in good order. White painted, light scuffing to right hand side wall."
  Parsing:
    "green painted" → description of element 1
    "in good order" → condition signal → closes element 1 description → condition: "In good order"
    "white painted" → new descriptive term → starts element 2 (sub-item)
    "light scuffing to right hand side wall" → condition of element 2
       ("right hand side wall" = location of scuffing, stays in condition)
  → main:   description="Green painted"   condition="In good order"
  → sub[0]: description="White painted"   condition="Light scuffing to right hand side wall"
  ✗ WRONG would be: merging "green painted" + "white painted" into one description
  ✗ WRONG would be: making "right hand side wall" a sub-item description

EXAMPLE 2 — Door and frame with different conditions → main + 1 sub-item:
  "Door and frame. White UPVC door, chrome lever handle … in good order.
   White painted timber frame, chrome hinges … light scuffing to base."
  → main:   description="White UPVC door\nChrome lever handle"           condition="In good order"
  → sub[0]: description="White painted timber frame\nChrome hinges"      condition="Light scuffing to base"

EXAMPLE 3 — Three elements → main + 2 sub-items:
  "Window and frame. White UPVC frame, chrome handle … in good order.
   White net curtain … in good order.
   White roller blind … one slat cracked."
  → main:   description="White UPVC frame\nChrome handle"  condition="In good order"
  → sub[0]: description="White net curtain"                condition="In good order"
  → sub[1]: description="White roller blind"               condition="One slat cracked"

EXAMPLE 4 — Multiple components, ONE shared condition → NOT a sub-item:
  "Ceiling. White emulsion, coving to perimeter … in good order."
  → description="White emulsion\nCoving to perimeter"  condition="In good order"
  (No text after the condition → no sub-item needed.)

EXAMPLE 5 — Defect with location qualifier → ONE element, no sub-item:
  "Walls. White emulsion. Light scuffing to base of wall throughout."
  → description="White emulsion"   condition="Light scuffing to base of wall throughout"
  ("to base of wall throughout" qualifies the location → all stays in condition)

══════════════════════════════════════════════════════
AMENDMENT RULES — correcting or extending a previously-filled item
══════════════════════════════════════════════════════
The clerk may amend or extend an already-described item using these commands:

  PRIMARY FORMAT (preferred):
  "Amend [item name] description [new content]"   → overwrite description only
  "Amend [item name] condition [new content]"     → overwrite condition only
  "Add to [item name] description [new content]"  → append to description only
  "Add to [item name] condition [new content]"    → append to condition only

  LEGACY FORMAT (also accepted):
  "Return to [item name], amend description, [new text]"
  "Return to [item name], amend condition, [new text]"
  "Return to [item name], add to description, [new text]"
  "Return to [item name], add to condition, [new text]"
  "Return to [item name], add to condition for [new text]"  — "for" is a filler word; treat as above
  "Return to [item name], amend, [new text]"  — overwrite both fields
  "Return to [item name], add, [new text]"    — append to both fields
  "Return to [item name], add sub item [description and condition]"   (also accepted: "add sub-item")
      → creates a new _subs entry on the named item; parse description/condition using the
         same sub-item rules. Do NOT include _descAction or _condAction — only output _subs.
      → For the sub-item content, split description from condition using the same condition
         signal phrases listed above — including defect words such as "loose", "broken",
         "missing", "stiff", "tight" etc. which are always condition, not description.

  Example: "Return to Contents, add sub item, chrome doorstop, slightly loose."
    → Locate the item named "Contents" and append a sub-item:
       _subs: [{{"description": "Chrome doorstop", "condition": "Slightly loose"}}]
    ("slightly loose" is a defect observation → condition, not description)

══════════════════════════════════════════════════════
CRITICAL — "RETURN TO" REDIRECTS MUST NEVER DUPLICATE CONTENT
══════════════════════════════════════════════════════
A "Return to [item], amend/add to/add sub item, [text]" command can appear ANYWHERE in the
dictation — including in the middle of a different item's sub-item list, or after several
sub-items have already been added to the CURRENT item. The instant this command is spoken:
  - CLOSE the element that was open at that moment (the current item OR whichever sub-item
    was most recently being filled). Its description/condition are done — nothing more is
    added to them.
  - Everything after the command belongs EXCLUSIVELY to the NAMED TARGET item's field.
  - The redirected text must appear in your JSON output ONCE, on the target item only.
    Do NOT also leave it (or a copy of it) on the item/sub-item that was open before the
    command was spoken. That would output the same observation twice — never do this.

  Example — redirect fired partway through a Contents sub-item chain:
    "Contents. White thermostat, in good order. Add sub item. Black doormat, used condition.
     Return to Flooring, add to condition, slight lifting left hand side next to entry."
    → Contents:       description="White thermostat"  condition="In good order"
      Contents _subs: [{{"description": "Black doormat", "condition": "Used condition"}}]
                       (the doormat sub-item's condition is "Used condition" ONLY — it does
                        NOT also contain "slight lifting…")
    → Flooring:       {{"condition": "Slight lifting left hand side next to entry", "_condAction": "append"}}
    ✗ WRONG: writing "Slight lifting left hand side next to entry" into the doormat sub-item's
      condition as well as into Flooring — this duplicates the observation in two places.

When you detect any amendment phrase, include these optional action flags in that item's JSON:
  "_descAction": "overwrite"  → caller will replace the existing description
  "_descAction": "append"     → caller will append this to the existing description
  "_condAction": "overwrite"  → caller will replace the existing condition
  "_condAction": "append"     → caller will append this to the existing condition

If no amendment phrase — omit the action flags entirely (default behaviour = fill only if empty).
"Amend [item]" with no field specified → set BOTH _descAction and _condAction to "overwrite".
"Add to [item]" with no field specified → set BOTH _descAction and _condAction to "append".

{_CONDITION_WORDS}
{_DESCRIPTION_VOCABULARY}
{retry_note}
Return ONLY valid JSON — no markdown, no extra text.
Items without sub-items use the flat shape. Items WITH sub-items include the "_subs" array.
Amendment flags are optional — only include when the clerk explicitly amends/adds.
The "_delete" flag is only included when the clerk says "Delete Item" or "Not Applicable" for that item.
{{
  "<itemId>": {{
    "description": "...",
    "condition": "..."
  }},
  "<deletedItemId>": {{
    "_delete": true
  }},
  "<amendedItemId>": {{
    "description": "replacement or addition text",
    "condition": "replacement or addition text",
    "_descAction": "overwrite",
    "_condAction": "append"
  }},
  "<itemIdWithSubs>": {{
    "description": "first element description",
    "condition": "first element condition",
    "_subs": [
      {{ "description": "second element description", "condition": "second element condition" }},
      {{ "description": "third element description", "condition": "third element condition" }}
    ]
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=8000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()

    stop_reason = getattr(message, 'stop_reason', None)
    if stop_reason == 'max_tokens':
        print(f'[_claude_fill_room] output truncated at max_tokens — raw[:400]: {raw[:400]}')
        raise ValueError('AI response was too long and got cut off — please try again or record fewer items at once')

    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError as e:
        print(f'[_claude_fill_room] JSON parse error (stop_reason={stop_reason}): {e} — raw[:400]: {raw[:400]}')
        raise ValueError('AI returned an invalid response — please try again')


def _claude_fill_room_checkout(transcript: str, section_name: str, items: list) -> dict:
    """
    Check-out version of _claude_fill_room.
    Items may include existing sub-items (with _sid + description) for routing.
    The clerk names an item (or sub-item) then states the check-out condition verbatim.

    Returns: { itemId: { "checkOutCondition": "..." } }
          or { itemId: { "_subs": [{ "_sid": "...", "checkOutCondition": "..." }] } }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    # Build items list with sub-items for the prompt
    lines = []
    for item in items:
        lines.append(f'  - ID: "{item["id"]}", Name: "{item["name"]}"')
        subs = item.get('subs', [])
        for sub in subs:
            desc = (sub.get('description') or '').strip()
            if desc:
                lines.append(f'    Sub-item: _sid="{sub["_sid"]}", Description: "{desc}"')
    items_list = '\n'.join(lines)

    prompt = f"""You are processing a UK property CHECK-OUT inspection dictation for a single room.

The clerk walks through the room describing each item's condition at the END of the tenancy.
Item names act as CHAPTER HEADINGS — everything said after an item name fills that item's check-out condition.
If an item has sub-items listed below it (indented), the clerk may name a sub-item by its description to target it specifically.

Room: {section_name}

Items to fill (sub-items are indented below their parent):
{items_list}

Transcript:
"{transcript}"

VERBATIM RULES — absolute, no exceptions:
1. Use the EXACT words the clerk spoke for check-out conditions. Do NOT interpret, condense, or paraphrase.
   - "2 x bulbs expired" → "2 x bulbs expired"  (NOT just "expired")
   - ONLY remove filler sounds: um, uh, er, errr, umm, erm
   - Clear false starts only (e.g. "white — white door" → "white door")
2. Convert spoken numbers to numerals: "two" → "2", "three" → "3"
3. Format quantities as "N x item": "two bulbs" → "2 x bulbs"
4. If the clerk names an item directly: fill its "checkOutCondition" field.
5. If the clerk names a sub-item (matching its Description): fill that sub-item's "checkOutCondition"
   and include it under the parent item's "_subs" array, using the exact _sid shown above.
6. Capitalise the first word of each observation.
7. Only fill items/sub-items that are mentioned. Omit everything else.
8. {_UK_SPELLING_RULE}
9. {_multi_component_rule("a checkOutCondition")}
10. REPEATED CONTENT: the transcript is stitched from several clips and may contain the same
    passage twice (overlapping recordings or the clerk repeating themselves). If the same or
    nearly the same wording appears more than once for an item, use it ONCE only — never
    output the same observation twice.
11. "AS INVENTORY+" PREFIX — MANDATORY, no exceptions: every checkOutCondition you output MUST
    start with the exact first line "As Inventory+", followed by the clerk's words on the next
    line(s) — for both main items and sub-items. This applies even when the clerk's words are
    brief or the condition is unchanged.
    CORRECT:   "As Inventory+\nScuff to bottom panel"
    INCORRECT: "Scuff to bottom panel"   (missing the required prefix line)
    If the clerk already said "as inventory" or "as inventory plus" themselves, do not duplicate
    it — output "As Inventory+" once, followed by anything else they said.

Return ONLY valid JSON — no markdown, no extra text.
Use "checkOutCondition" (not "condition") for all fields.
Example output:
{{
  "<itemId>": {{
    "checkOutCondition": "As Inventory+\\nclerk's exact words"
  }},
  "<itemIdWithSubs>": {{
    "_subs": [
      {{ "_sid": "exact_sid_from_above", "checkOutCondition": "As Inventory+\\nclerk's exact words" }}
    ]
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=8000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()

    stop_reason = getattr(message, 'stop_reason', None)
    if stop_reason == 'max_tokens':
        print(f'[_claude_fill_room_checkout] output truncated at max_tokens — raw[:400]: {raw[:400]}')
        raise ValueError('AI response was too long and got cut off — please try again or record fewer items at once')

    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError as e:
        print(f'[_claude_fill_room_checkout] JSON parse error (stop_reason={stop_reason}): {e} — raw[:400]: {raw[:400]}')
        raise ValueError('AI returned an invalid response — please try again')


def _claude_fill_room_damage(transcript: str, section_name: str, items: list, processed_ids: list = None, retry_note: str = '') -> dict:
    """
    Damage Report version of _claude_fill_room.
    Item names act as chapter headings; everything the clerk says maps to 'condition' only.
    No description field is ever populated.

    Returns: { itemId: { 'condition': '...' } }
          or { itemId: { '_subs': [{ 'condition': '...' }] } }
    retry_note: appended to the prompt when re-attempting after a detected sub-item mismatch.
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  - ID: "{item["id"]}", Name: "{item["name"]}"'
        for item in items
    )

    processed_note = ''
    if processed_ids:
        id_list = ', '.join(f'"{pid}"' for pid in processed_ids)
        processed_note = f"""
══════════════════════════════════════════════════════
ALREADY-TRANSCRIBED ITEMS — skip unless explicitly amended
══════════════════════════════════════════════════════
The following item IDs were filled in a previous pass and already have condition content:
  {id_list}

Omit these items entirely UNLESS the clerk explicitly amends, adds to, creates a sub-item on,
or deletes them. Accepted patterns:

  OVERWRITE (_condAction = "overwrite"):
    "Amend [item name] condition [content]" | "[item name]. Amend condition. [content]"
    "Return to [item name], amend condition, [content]"

  APPEND (_condAction = "append"):
    "Add to [item name] condition [content]" | "[item name]. Add to condition. [content]"
    "Return to [item name], add to condition, [content]"

  SUB-ITEM (output only _subs):
    "[item name]. Sub-item. [damage]" | "Return to [item name], add sub-item, [damage]"

  DELETE (_delete: true):
    "[item name]. Delete item." | "[item name]. Not Applicable." | "[item name]. Not seen."
    ("Not seen" only deletes when IMMEDIATELY after the item name — not when inside a description)

CHAPTER-HEADING PATTERN: If the clerk names an already-transcribed item as a chapter heading
and IMMEDIATELY follows with a command word ("Amend", "Add", "Sub-item"), treat it as explicit.
  Example: "Door and frame. Amend condition. Chip to base."
    → {{"<doorId>": {{"condition": "Chip to base", "_condAction": "overwrite"}}}}
"""

    prompt = f"""You are processing a UK property DAMAGE REPORT inspection dictation for a single room.

The clerk walks through the room and says each item name followed by a description of the damage.
Item names act as CHAPTER HEADINGS — everything said after an item name goes into that item's
"condition" field. There is NO description field in a damage report.

Room: {section_name}

Items (use the ID as the JSON key, match by Name):
{items_list}
{processed_note}
Transcript:
"{transcript}"

RULES:
1. CHAPTER HEADING MATCHING — two tiers, applied in order:
   TIER 1 (exact): spoken phrase matches the full item name (case-insensitive; "&"/"and" interchangeable;
     singular/plural of the SAME root word counts as exact — "Content" matches "Contents", "Curtain"
     matches "Curtains" — but a genuinely different word like "Floor" does NOT match "Flooring").
     Also treat Whisper's common mishearing "Sealing" as "Ceiling" — they are the same heading.
   TIER 2 (unique partial): spoken phrase is a distinctive word/phrase found in exactly ONE item name
     and no other — e.g. "Base units" → "Kitchen Base Units" if that is the only match.
     If the phrase could match more than one item, do NOT use Tier 2 — leave content with current item.
   UNRECOGNISED HEADINGS: if a standalone phrase matches nothing by either tier, skip it and
     everything the clerk says about it until the next recognised heading. Do not attach skipped
     content to any other item.
2. Everything the clerk says after an item name is DAMAGE CONDITION — put it all in "condition".
   Never use a "description" field.
3. VERBATIM: use the clerk's exact words. Only remove filler sounds (um, uh, er, errr, umm, erm)
   and clear false starts (e.g. "scuff — scuff to base" → "scuff to base").
4. {_multi_component_rule("a damage condition")}
5. Convert spoken numbers to numerals: "two" → "2". Format quantities as "N x item".
6. Capitalise the first word of each line.
7. Only fill items that are mentioned. Omit unmentioned items entirely.
8. If a single component has multiple distinct damage observations, each goes on its own line.
9. {_UK_SPELLING_RULE}
10. REPEATED CONTENT: the transcript is stitched from several clips and may contain the same
    passage twice (overlapping recordings or the clerk repeating themselves). If the same or
    nearly the same wording appears more than once for an item, use it ONCE only — never
    output the same observation twice. A repeated plain mention of an already-covered item
    is NEVER an amendment — only the explicit command words above are.

══════════════════════════════════════════════════════
DELETE ITEM
══════════════════════════════════════════════════════
The clerk may say "[item name] Delete Item", "[item name] Not Applicable", or
"[item name] Not seen" to mark an item as not present.
  → Set "_delete": true on that item. Do NOT fill condition.

CRITICAL CONTEXT RULE FOR "not seen":
"Not seen" is a delete command ONLY when it appears IMMEDIATELY after an item title with
no intervening description. If it appears inside a longer passage about the item, it is
descriptive content and must NOT trigger deletion.
  ✓ DELETE: "Windows & Frames. Not seen."  → _delete: true
  ✗ NOT DELETE: "model and serial number not seen" (within a description) → dictate normally

══════════════════════════════════════════════════════
SUB-ITEMS
══════════════════════════════════════════════════════
The clerk may use ANY of these phrases to start a new damage element within the same item:
  "sub-item", "sub item", "next sub-item", "next sub item",
  "add sub item", "add sub-item", "add a sub item"
Each sub-item has its own "condition" only. No description.

This trigger is ABSOLUTE — it fires every time it is spoken, no exceptions. It still applies
even if the current item's condition list already has many lines stacked up (don't lose the
trigger inside a long list), and even if the sub-item's wording repeats an earlier observation
verbatim (matching wording is not a reason to merge it back into the main item — only skip
content when there was NO explicit trigger and the passage is a genuine stitching duplicate).

"Return to [item name], add sub-item [damage content]"
  → Creates a new _subs entry on the named item. Only condition, no _descAction/_condAction.

══════════════════════════════════════════════════════
AMENDMENT COMMANDS
══════════════════════════════════════════════════════
"Amend [item name] condition [new content]"       → overwrite condition (_condAction: "overwrite")
"Add to [item name] condition [new content]"      → append to condition (_condAction: "append")
"Return to [item name], amend condition, [text]"  → overwrite condition (_condAction: "overwrite")
"Return to [item name], add to condition, [text]" → append to condition (_condAction: "append")

CRITICAL — REDIRECTS MUST NEVER DUPLICATE CONTENT:
A "Return to [item], ..." command can fire anywhere, including mid-way through another item's
sub-item list. The moment it fires, CLOSE whatever element (item or sub-item) was currently open
— its condition is done, nothing more is added to it. Everything after the command belongs
EXCLUSIVELY to the named target item. The redirected text appears ONCE, on the target item only
— never leave a copy of it on the item/sub-item that was open before the command was spoken.
{retry_note}
Return ONLY valid JSON — no markdown, no extra text.
{{
  "<itemId>": {{
    "condition": "Damage observation one\\nDamage observation two"
  }},
  "<deletedItemId>": {{
    "_delete": true
  }},
  "<amendedItemId>": {{
    "condition": "replacement or addition",
    "_condAction": "overwrite"
  }},
  "<itemWithSubs>": {{
    "condition": "Main element damage",
    "_subs": [
      {{ "condition": "Second element damage" }},
      {{ "condition": "Third element damage" }}
    ]
  }}
}}"""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=8000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()

    stop_reason = getattr(message, 'stop_reason', None)
    if stop_reason == 'max_tokens':
        print(f'[_claude_fill_room_damage] output truncated at max_tokens — raw[:400]: {raw[:400]}')
        raise ValueError('AI response was too long and got cut off — please try again or record fewer items at once')

    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError as e:
        print(f'[_claude_fill_room_damage] JSON parse error (stop_reason={stop_reason}): {e} — raw[:400]: {raw[:400]}')
        raise ValueError('AI returned an invalid response — please try again')


def _claude_fill_fixed_section(transcript: str, section_name: str, section_type: str, items: list) -> dict:
    """
    Fill a fixed section's items from a continuous dictation transcript.
    Like _claude_fill_room but returns section-type-specific field names.

    items: [{ 'id': str, 'name': str }]

    Return shapes per section type:
      condition_summary        → { "condition": "..." }
      cleaning_summary         → { "cleanlinessNotes": "..." }
      fire_door_safety /
        health_safety /
        smoke_alarms           → { "notes": "...", "answer": "Yes"|"No"|"" }
      keys                     → { "description": "..." }
      meter_readings            → { "locationSerial": "...", "reading": "..." }
    """
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    items_list = '\n'.join(
        f'  - ID: "{item["id"]}", Name: "{item["name"]}"'
        for item in items
    )

    # Build section-specific instructions AND a concrete example output so the model
    # can follow by example rather than abstract description.
    # The \\n in field_example strings becomes a literal \n in the prompt, which is
    # exactly the JSON escape sequence needed to produce a newline in the field value.

    if section_type == 'condition_summary':
        field_instructions = (
            'Extract the condition observations into "condition". '
            'Each separate observation MUST go on its own line — use the \\n escape sequence between them. '
            'NEVER run multiple observations together as a single sentence. '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "42": {"condition": "Some wear to carpet throughout\\nScuff marks to base of walls\\nDoor handle loose"}\n'
            '}'
        )
    elif section_type == 'cleaning_summary':
        field_instructions = (
            'The clerk mentions the CATEGORY or LINE NAME first (e.g. "flooring", "kitchen surfaces"), '
            'then describes the cleanliness observation. Match the category name to the closest item, '
            'then fill "cleanlinessNotes" with the observation that follows. '
            'Each separate observation MUST go on its own line — use the \\n escape sequence between them. '
            'NEVER run multiple observations together as a single sentence. '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "55": {"cleanlinessNotes": "Grease marks to hob surface\\nLight limescale to sink taps"}\n'
            '}'
        )
    elif section_type in ('fire_door_safety', 'health_safety', 'smoke_alarms'):
        field_instructions = (
            'Extract observations into "notes". '
            'Each separate observation MUST go on its own line — use the \\n escape sequence between them. '
            'If the clerk gives a yes/no answer (e.g. "yes", "no", "working", "not working"), '
            'put "Yes" or "No" in "answer"; otherwise leave "answer" as an empty string. '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "61": {"notes": "Fitted to ceiling in hallway\\nTested and working", "answer": "Yes"}\n'
            '}'
        )
    elif section_type == 'keys':
        field_instructions = (
            'Extract key descriptions into "description". '
            'If the clerk mentions anything about collecting, receiving, handing over, or returning keys — '
            'regardless of who from or to — put this EXACTLY as spoken on the FIRST line. '
            'This line must always be included when the clerk says it '
            '(e.g. "Keys collected from and returned to Yellands Estates", "Keys handed to tenant", '
            '"Keys received from landlord"). '
            'Each key TYPE must be on its own line — use the \\n escape sequence between them. '
            'Format each key line as "N x [key type]". '
            'Convert spoken numbers to numerals ("two" → "2"). '
            'Use the EXACT words the clerk spoke.'
        )
        field_example = (
            '{\n'
            '  "70": {"description": "Keys collected from and returned to Yellands Estates\\n1 x Yale key\\n1 x Chubb key\\n2 x fob"}\n'
            '}'
        )
    elif section_type == 'meter_readings':
        field_instructions = (
            'The clerk provides explicit headings for each meter (e.g. "Gas meter", "Electricity meter", '
            '"Water meter"). Match the heading to the closest item by name. Then fill: '
            '"locationSerial" — the location on the FIRST line and serial number on the SECOND line, '
            'separated by the \\n escape sequence, formatted EXACTLY as: '
            '"Located to [location]\\nSerial Number: [number]" (omit whichever part is not mentioned); '
            '"reading" — the numeric reading value only, no units. '
            'CRITICAL: locationSerial MUST use \\n between the Located line and the Serial Number line — '
            'never put them on a single line separated by a space or comma. '
            'Use the EXACT words the clerk spoke for location and serial number descriptions.'
        )
        field_example = (
            '{\n'
            '  "81": {"locationSerial": "Located to entrance hallway storage cupboard\\nSerial Number: AB123456", "reading": "8234.5"},\n'
            '  "82": {"locationSerial": "Located to kitchen utility area\\nSerial Number: GX987654", "reading": "1045"}\n'
            '}'
        )
    else:
        field_instructions = 'Extract all observations into "notes". Use the EXACT words the clerk spoke.'
        field_example = '{\n  "<itemId>": {"notes": "Observation text here"}\n}'

    prompt = f"""You are processing a UK property inventory inspection dictation for a fixed section.

The clerk spoke each item name aloud followed by their observations.
Item names act as CHAPTER HEADINGS — everything said after an item name belongs to that item, until the next item name is spoken.

Section: {section_name}
Section type: {section_type}

Items to fill (use the ID as the JSON key, match by Name):
{items_list}

Transcript:
"{transcript}"

RULES:
1. Match each passage to the closest item name. The clerk may abbreviate — use fuzzy matching.
2. {field_instructions}
3. CRITICAL: Use the EXACT words the clerk spoke. Do not rephrase, paraphrase, or substitute synonyms.
   - "good order" → "Good order" (NOT "Good condition")
   - "fair wear and tear" → "Fair wear and tear"
4. ONLY remove filler sounds (um, uh, er, errr, umm, erm) and clear false starts where the clerk immediately restarts the same phrase. Do NOT remove, shorten, or paraphrase any actual content — reproduce the clerk's words in full.
5. Only fill items that are mentioned. Omit unmentioned items entirely from the output.
6. {_UK_SPELLING_RULE}
7. Capitalise the first word of each line.

LINE BREAKS — THIS IS CRITICAL:
Use the JSON escape sequence \\n (backslash + n) inside string values whenever a new line is needed.
NEVER collapse multiple pieces of information into a single run-on sentence.
Follow the example output format EXACTLY.

Example output format for this section type:
{field_example}

Return ONLY valid JSON matching that shape — no markdown, no extra text, real item IDs only."""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    raw = message.content[0].text.strip()
    raw = raw.replace('```json', '').replace('```', '').strip()
    try:
        return json.loads(_sanitise_json(raw)), message
    except json.JSONDecodeError:
        print(f'[_claude_fill_fixed_section] JSON parse error: {raw[:200]}')
        return {}, message


@transcribe_bp.route('/room', methods=['POST'])
@jwt_required()
def transcribe_room():
    """
    Per-room dictation — the clerk records the whole room in one go (with pause/resume),
    then presses 'AI Transcribe' in the app to fill all item fields at once.

    This replaces the old 'ai_processing' server-side flow. All processing now happens
    on demand from the app before syncing.

    Request JSON:
    {
      "clips":       [{"audio": "<base64>", "mimeType": "audio/m4a"}, ...],
      "sectionName": "Living Room",
      "sectionKey":  "123",
      "items": [
        {"id": "456", "name": "Ceiling", "hasCondition": true, "hasDescription": true},
        ...
      ]
    }

    Response JSON:
    {
      "transcript": "Ceiling. Good condition, white painted...",
      "filled": {
        "456": {"description": "White painted", "condition": "In good order"}
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    clips              = data.get('clips', [])
    section_name       = data.get('sectionName', 'Room')
    section_type       = data.get('sectionType', 'room')   # 'room' | fixed-section types
    items              = data.get('items', [])
    is_check_out       = bool(data.get('isCheckOut', False))
    is_damage_report   = bool(data.get('isDamageReport', False))
    processed_item_ids = data.get('processedItemIds') or []
    inspection_id      = int(data['inspectionId']) if data.get('inspectionId') else None

    if not clips:
        return jsonify({'error': 'No audio clips provided'}), 400
    if not items:
        return jsonify({'error': 'No items provided'}), 400

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'OPENAI_API_KEY not configured on server'}), 503
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # Transcribe each clip with Whisper, collect actual durations
    transcripts = []
    total_audio_secs = 0.0
    for i, clip in enumerate(clips):
        audio_b64 = clip.get('audio')
        mime_type = clip.get('mimeType', 'audio/m4a')
        if not audio_b64:
            continue
        try:
            audio_bytes = base64.b64decode(audio_b64)
            text, secs = _whisper_transcribe(audio_bytes, mime_type)
            if text:
                transcripts.append(text.strip())
                total_audio_secs += secs
        except Exception as e:
            print(f'[transcribe/room] clip {i} whisper error: {e}')

    # Drop consecutive identical clip transcripts — duplicate clip rows can be
    # restored from the mobile app's local DB after a remount, and a duplicated
    # passage in the joined transcript gets faithfully doubled into the fill.
    deduped = []
    for t in transcripts:
        if deduped and deduped[-1].strip() == t.strip():
            print('[transcribe/room] dropped duplicate adjacent clip transcript')
            continue
        deduped.append(t)
    full_transcript = ' '.join(deduped)
    if not full_transcript:
        return jsonify({'error': 'No speech detected in recording'}), 422

    try:
        if section_type == 'room':
            if is_check_out:
                filled, fill_msg = _claude_fill_room_checkout(full_transcript, section_name, items)
            elif is_damage_report:
                filled, fill_msg = _fill_room_with_subitem_retry(
                    _claude_fill_room_damage, full_transcript, section_name, items,
                    processed_item_ids, 'transcribe/room damage'
                )
            else:
                filled, fill_msg = _fill_room_with_subitem_retry(
                    _claude_fill_room, full_transcript, section_name, items,
                    processed_item_ids, 'transcribe/room'
                )
            # Deterministic dedupe of repeated lines / cross-field duplicates —
            # applies to all room fill types including check-out.
            filled = _dedupe_filled(filled)
            # Cross-item safety net: strip redirected text left behind on whatever
            # item/sub-item was open before a "Return to X, add to ..." command fired.
            filled = _dedupe_redirect_leaks(filled)
        else:
            filled, fill_msg = _claude_fill_fixed_section(full_transcript, section_name, section_type, items)
    except Exception as e:
        print(f'[transcribe/room] claude error: {e}')
        return jsonify({'error': f'AI fill error: {str(e)}'}), 500

    # Log usage — previously missing for room-mode transcriptions
    try:
        usage_log = TranscriptionUsage(
            call_type     = 'room',
            inspection_id = inspection_id,
            user_id       = int(get_jwt_identity()),
            audio_seconds = total_audio_secs,
            input_tokens  = fill_msg.usage.input_tokens  if fill_msg and fill_msg.usage else 0,
            output_tokens = fill_msg.usage.output_tokens if fill_msg and fill_msg.usage else 0,
            section_type  = section_type,
        )
        db.session.add(usage_log)
        db.session.commit()
    except Exception:
        pass  # never let logging break the response

    return jsonify({
        'transcript': full_transcript,
        'filled':     filled,
    })


def _is_good_order(condition: str) -> bool:
    """Return True if a condition string indicates no issues (blank or good-state phrase)."""
    if not condition:
        return True
    c = condition.strip().lower().rstrip('.')
    good_phrases = {
        'in good order', 'good order', 'in very good order', 'very good order',
        'in excellent order', 'excellent order', 'as new', 'as inventory',
        'in good condition', 'good condition', 'in clean condition', 'clean condition',
        'in fair order', 'fair order', 'in fair condition', 'fair condition',
    }
    # Condition may have multiple lines — check each line
    lines = [l.strip().lower().rstrip('.') for l in c.split('\n') if l.strip()]
    if not lines:
        return True
    # Consider "good order" only when ALL lines are good-state phrases
    return all(l in good_phrases for l in lines)


# ── Minor-wear filtering for condition summaries ───────────────────────────
# The prompt already tells the model to EXCLUDE "light/slight/minor/superficial"
# marks as normal cosmetic wear, but real production summaries show it isn't
# reliably followed — some ran 150-200+ lines, a large fraction of it exactly
# this class of line ("Light overpainted defects", "Light rub marks", "Slight
# bubbling"...). Filter deterministically before the LLM ever sees them,
# mirroring the existing _is_good_order() pattern, rather than trusting the
# model to keep applying a rule it's already shown it doesn't apply reliably.
#
# Genuinely significant categories survive regardless of a "light"/"slight"
# qualifier — a hairline crack or light water staining is still worth flagging
# even when described as minor in degree; only pure cosmetic wear gets dropped.
_MINOR_QUALIFIER_RE = _re.compile(
    r'\b(?:light(?:ly)?|slight(?:ly)?|minor|superficial(?:ly)?|small|odd|occasional)\b',
    _re.IGNORECASE,
)
_ALWAYS_SIGNIFICANT_RE = _re.compile(
    r'\b(?:damp|mould|mold|water\s*(?:damage|ingress|staining)|tide\s*mark|leak(?:ing|s)?|'
    r'crack(?:s|ing)?|structural|settlement|dropped\s+hinge|warp(?:ed|ing)?|'
    r'no\s+power|not\s+work(?:ing)?|does\s+not\s+(?:work|open|close|operate|function)|'
    r'seized|jammed|missing|hole(?:s)?|burn(?:s|t)?|gouge(?:s|d)?|broken|failed|defective)\b',
    _re.IGNORECASE,
)


def _filter_minor_wear_lines(condition: str) -> str:
    """
    Drop lines that are purely minor cosmetic wear (light/slight/minor/
    superficial, with no genuinely significant category present) — keep
    everything else, including a "light"-qualified line that also touches
    damp/mould/water, cracks, structural issues, non-functional items,
    missing items, or physical damage.
    """
    if not condition:
        return condition
    kept = []
    for line in condition.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if _ALWAYS_SIGNIFICANT_RE.search(stripped) or not _MINOR_QUALIFIER_RE.search(stripped):
            kept.append(stripped)
    return '\n'.join(kept)


def _filter_issues_only(sections: list) -> list:
    """
    Remove items where condition is blank, a good-state phrase, or reduces to
    nothing once minor-cosmetic-wear-only lines are filtered out. Items are
    kept if the main condition OR any sub's condition has an actual issue.
    Returns a new sections list with only rooms/items that have real issues.
    """
    filtered = []
    for section in sections:
        kept_items = []
        for item in section.get('items', []):
            cond = _filter_minor_wear_lines((item.get('condition') or '').strip())
            subs = item.get('subs', [])

            main_has_issue = bool(cond) and not _is_good_order(cond)
            issue_subs = []
            for s in subs:
                sub_cond = _filter_minor_wear_lines((s.get('condition') or '').strip())
                if sub_cond and not _is_good_order(sub_cond):
                    issue_subs.append({**s, 'condition': sub_cond})

            if main_has_issue or issue_subs:
                kept = dict(item)
                kept['subs'] = issue_subs
                kept['condition'] = cond if main_has_issue else ''  # sub(s) have the issue; don't echo good-order main cond
                kept_items.append(kept)

        if kept_items:
            filtered.append({'name': section.get('name', ''), 'items': kept_items})
    return filtered


@transcribe_bp.route('/condition-summary', methods=['POST'])
@jwt_required()
def generate_condition_summary():
    """
    Generate a Condition Summary from the filled room inspection data.
    No audio involved — reads existing report content and synthesises notable issues.

    Request JSON:
    {
      "inspectionId": 123,
      "sections": [
        {
          "name": "Kitchen",
          "items": [
            { "name": "Ceiling", "description": "White emulsion", "condition": "In good order" },
            { "name": "Floor",   "description": "Grey vinyl",     "condition": "Worn to entrance",
              "subs": [{ "description": "Silver threshold", "condition": "Light scratching" }] }
          ]
        }
      ],
      "summaryItems": [
        { "id": "fs_2_0", "name": "General Property Condition" }
      ]
    }

    Response JSON:
    {
      "filled": {
        "fs_2_0": { "condition": "Worn vinyl flooring to Kitchen entrance\\nLight scuffing to walls in Hallway" }
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    sections          = data.get('sections', [])
    summary_items     = data.get('summaryItems', [])
    inspection_id     = int(data['inspectionId']) if data.get('inspectionId') else None
    prop_details      = data.get('propertyDetails') or {}
    is_check_out      = bool(data.get('isCheckOut'))
    check_in_sections = data.get('checkInSections') or []

    if not sections:
        return jsonify({'error': 'No inspection data provided'}), 400
    if not summary_items:
        return jsonify({'error': 'No condition summary items provided'}), 400

    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on server'}), 503

    # ── For Check Out: merge CI baseline into CO data ─────────────────────
    # Each merged item carries TWO distinct fields instead of one blended
    # "condition":
    #   check_in_condition — the ORIGINAL check-in finding, kept only when it's
    #     a real issue (good-order/blank is dropped, same filter as check-in mode)
    #   check_out_new      — whatever the clerk recorded at check-out, with the
    #     standard "As Inventory+" boilerplate prefix stripped off first, so an
    #     item that's genuinely unchanged from check-in ends up empty here
    #     rather than showing the boilerplate as if it were a new finding.
    # An item is dropped entirely once both are empty and it has no sub-items
    # with content — there is nothing left worth summarising.
    if is_check_out and check_in_sections:
        ci_lookup: dict = {}
        for ci_sec in check_in_sections:
            for ci_item in ci_sec.get('items', []):
                key = (ci_sec.get('name', '').lower(), ci_item.get('name', '').lower())
                ci_lookup[key] = ci_item

        def _new_at_checkout(raw: str) -> str:
            stripped = _AS_INVENTORY_RE.sub('', (raw or '')).strip().strip(',').strip()
            stripped = _filter_minor_wear_lines(stripped)
            return '' if _is_good_order(stripped) else stripped

        def _major_at_checkin(raw: str) -> str:
            raw = _filter_minor_wear_lines((raw or '').strip())
            return '' if _is_good_order(raw) else raw

        def _merge_subs(co_subs: list) -> list:
            merged_subs = []
            for sub in co_subs or []:
                new_finding = _new_at_checkout(sub.get('checkOutCondition') or sub.get('condition') or '')
                if new_finding or (sub.get('description') or '').strip():
                    merged_subs.append({'description': sub.get('description', ''), 'condition': new_finding})
            return merged_subs

        merged: list = []
        co_sec_names: set = set()
        for co_sec in sections:
            sec_name = co_sec.get('name', '')
            co_sec_names.add(sec_name.lower())
            merged_items: list = []
            covered: set = set()
            for item in co_sec.get('items', []):
                key = (sec_name.lower(), item.get('name', '').lower())
                covered.add(key)
                ci = ci_lookup.get(key, {})
                check_in_condition = _major_at_checkin(ci.get('condition', ''))
                check_out_new = _new_at_checkout(item.get('checkOutCondition') or item.get('condition') or '')
                merged_subs = _merge_subs(item.get('subs', []))
                if not (check_in_condition or check_out_new or merged_subs):
                    continue
                merged_items.append({
                    'name':               item.get('name', ''),
                    'description':        item.get('description') or ci.get('description', ''),
                    'check_in_condition': check_in_condition,
                    'check_out_new':      check_out_new,
                    'subs':               merged_subs,
                })
            # Add CI items for this room that have no CO entry — only if the CI finding is major
            for ci_sec in check_in_sections:
                if ci_sec.get('name', '').lower() == sec_name.lower():
                    for ci_item in ci_sec.get('items', []):
                        key = (sec_name.lower(), ci_item.get('name', '').lower())
                        if key in covered:
                            continue
                        covered.add(key)
                        check_in_condition = _major_at_checkin(ci_item.get('condition', ''))
                        if not check_in_condition:
                            continue
                        merged_items.append({
                            'name':               ci_item.get('name', ''),
                            'description':        ci_item.get('description', ''),
                            'check_in_condition': check_in_condition,
                            'check_out_new':      '',
                            'subs':               [],
                        })
            if merged_items:
                merged.append({'name': sec_name, 'items': merged_items})
        # Rooms only in CI (not visited at CO) — same major-issues-only filter
        for ci_sec in check_in_sections:
            if ci_sec.get('name', '').lower() not in co_sec_names:
                kept_items = []
                for ci_item in ci_sec.get('items', []):
                    check_in_condition = _major_at_checkin(ci_item.get('condition', ''))
                    if check_in_condition:
                        kept_items.append({
                            'name':               ci_item.get('name', ''),
                            'description':        ci_item.get('description', ''),
                            'check_in_condition': check_in_condition,
                            'check_out_new':      '',
                            'subs':               [],
                        })
                if kept_items:
                    merged.append({'name': ci_sec.get('name', ''), 'items': kept_items})
        sections = merged

    # ── For Check In: strip items that have no real issues ────────────────
    # Pre-filtering means Claude never sees "in good order" items, so it cannot
    # accidentally include them or route them to the wrong summary section.
    if not is_check_out:
        sections = _filter_issues_only(sections)

    # ── Build property description sentence ───────────────────────────────
    prop_type  = (prop_details.get('property_type') or '').strip()
    bedrooms   = prop_details.get('bedrooms')
    bathrooms  = prop_details.get('bathrooms')
    furnished  = (prop_details.get('furnished') or '').strip()
    address    = (prop_details.get('address') or '').strip()

    prop_parts = []
    if bedrooms is not None:
        prop_parts.append(f'{int(bedrooms)}-bedroom')
    if bathrooms is not None:
        prop_parts.append(f'{int(bathrooms)}-bathroom')
    if furnished:
        prop_parts.append(furnished.lower())
    if prop_type:
        prop_parts.append(prop_type.lower())

    if prop_parts:
        property_description = 'Property is a ' + ' '.join(prop_parts) + '.'
    elif address:
        property_description = f'Property at {address}.'
    else:
        property_description = 'Property details not provided.'

    # ── Format inspection findings as readable text ────────────────────────
    def _format_subs(subs: list, co_label: bool) -> list:
        out = []
        for sub in subs:
            sub_desc = (sub.get('description') or '').strip()
            sub_cond = (sub.get('condition') or '').strip()
            if not sub_desc and not sub_cond:
                continue
            sub_entry = '    ↳'
            if sub_desc:
                sub_entry += f' {sub_desc}'
            if sub_cond:
                sub_entry += f' | Check-out (new): {sub_cond}' if co_label else f' | {sub_cond}'
            out.append(sub_entry)
        return out

    lines = []
    for section in sections:
        sec_name  = section.get('name', 'Room')
        sec_items = section.get('items', [])
        if not sec_items:
            continue
        sec_lines = []
        for item in sec_items:
            item_name = item.get('name', 'Item')
            desc      = (item.get('description') or '').strip()

            if is_check_out:
                ci_cond = (item.get('check_in_condition') or '').strip()
                co_new  = (item.get('check_out_new') or '').strip()
                if not desc and not ci_cond and not co_new:
                    continue
                entry = f'  - {item_name}'
                if desc:
                    entry += f': {desc}'
                if ci_cond:
                    entry += f' | Check-in: {ci_cond}'
                if co_new:
                    entry += f' | Check-out (new): {co_new}'
                sec_lines.append(entry)
                sec_lines.extend(_format_subs(item.get('subs', []), co_label=True))
            else:
                cond = (item.get('condition') or '').strip()
                if not desc and not cond:
                    continue
                entry = f'  - {item_name}'
                if desc:
                    entry += f': {desc}'
                if cond:
                    entry += f' | {cond}'
                sec_lines.append(entry)
                sec_lines.extend(_format_subs(item.get('subs', []), co_label=False))
        if sec_lines:
            lines.append(f'\n=== {sec_name} ===')
            lines.extend(sec_lines)

    inspection_text = '\n'.join(lines) if lines else 'No room data available.'

    items_list = '\n'.join(
        f'  {i+1}. ID: "{item["id"]}", Name: "{item["name"]}"'
        for i, item in enumerate(summary_items)
    )

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

    if is_check_out:
        summary_type_label = 'Check Out Condition Summary'
        severity_rule = """\
4. TWO SOURCES PER ITEM — CHECK-IN CONTEXT vs CHECK-OUT NEW FINDING
   Each item below may show a "Check-in:" value and/or a "Check-out (new):" value.
   These mean DIFFERENT things — never blur them together:
   - "Check-in:" = a significant issue that was ALREADY present at the start of the tenancy.
     Trivial/good-order items have already been filtered out, so anything shown here is real.
   - "Check-out (new):" = what the clerk recorded when checking the property back in, with the
     standard "As Inventory+" boilerplate already stripped out. What remains is a genuinely NEW
     observation made at check-out — it is NOT a restatement of the check-in condition.

   Compose each item's line from whichever of the two is present:
   - Only "Check-in:" present   → report the pre-existing issue, noting it was already there.
     Example: "Chip to plaster above window (present at check-in)"
   - Only "Check-out (new):" present → report it as a new finding.
     Example: "Water staining to ceiling — new since check-in"
   - BOTH present → report both, making clear which is which, do not merge them into one claim.
     Example: "Crack to tile present at check-in; additional chip to sink surround noted at check-out"
   - An item with neither value has already been excluded — this should not occur.

   Do NOT invent a distinction that isn't in the data. Never describe something as "new" unless
   it appears under "Check-out (new):". Never describe something as pre-existing unless it
   appears under "Check-in:". Do NOT write vague placeholders like "In good order" — every item
   shown to you already has a real finding on at least one side.

4b. DISTIL — write a summary, not a transcript
   Each finding should be ONE concise line per item — do not copy condition notes verbatim.
   If either side lists several issues, write only the most significant one from that side.

4c. CONSOLIDATE — do not repeat the same issue across many rooms
   If the same minor "Check-out (new):" issue appears in most rooms, note it once under the
   most relevant room only rather than listing it under every room."""
        overview_prefix = 'Check out: '
    else:
        summary_type_label = 'Check In Condition Summary'
        severity_rule = """\
4. NOTEWORTHY THRESHOLD — what belongs in a condition summary
   You are writing for a client, landlord, or agent who wants a quick professional overview.
   This is a SUMMARY — not every detail from the inspection needs to appear here.
   Include ONLY findings that a property professional would flag as worth attention.

   INCLUDE (examples — not exhaustive):
   • Damage needing repair or replacement: chips to plaster, cracks to tiles or walls,
     holes, burns, gouges, broken fittings, damaged or failed glazing
   • Missing items or fittings that should be present
   • Non-functional items: no power, seized locks, jammed mechanisms, does not operate
   • Damp, mould, water damage, water ingress, tide marks
   • Significant staining — ingrained, large area, or from an identifiable cause (not light marks)
   • Peeling or flaking paint (not just lightly marked); failed silicone or grout
   • Structural observations: settlement cracks, dropped hinges, warped frames or doors
   • Anything clearly beyond normal fair wear and tear for a property of this type and age

   EXCLUDE — these must NEVER appear in a check-in condition summary:
   • Items in good order, fair order, excellent condition, as new, as inventory — already filtered
   • Light, slight, minor, or superficial marks — these are normal cosmetic wear
   • Fair wear and tear (even if the inspector mentioned it explicitly)
   • Observations that only confirm an item is working, complete, or functional
   • Serial numbers, model numbers, or purely descriptive notes with no condition defect

   WHEN IN DOUBT: omit it. A shorter, accurate summary is more useful than a long one
   padded with minor observations.

4b. DISTIL — write a summary, not a transcript
   Each finding should be ONE concise line — the single most important observation
   about that item in that room. Do NOT copy condition notes verbatim.
   If an item's condition mentions several issues, write only the most significant.
   Example — condition note: "Light surface scratching to hob plate\\nGrease build-up to surround"
   → Summary line: "Grease build-up to hob surround"  (skip the light scratch)

4c. CONSOLIDATE — do not repeat the same issue across many rooms
   If the same minor issue appears in most rooms (e.g., scuffs to walls throughout),
   either omit it entirely (if it is cosmetic/minor) or note it once under the most
   relevant room only — do not list it under every room."""
        overview_prefix = ''

    prompt = f"""You are writing a {summary_type_label} for a UK property inspection report.

════════════════════════════════════════════════════
PHASE 1 — INTERNALIZE THE SUMMARY SECTIONS
Before reading the inspection data, memorize the following sections.
Every finding must be assigned to EXACTLY ONE section. No duplication.
════════════════════════════════════════════════════

PROPERTY: {property_description}

SUMMARY SECTIONS (numbered for reference):
{items_list}

CATEGORY GUIDE — match by INSPECTION ITEM NAME (the label before the colon in the data below):
  Assign each inspection item to the summary section whose name most closely matches
  the ITEM NAME. Use the examples below as a guide for common item names:

  • Overview / Property Description  → no inspection items; use property details only
  • Decorative Order                 → items named: Decorative Order, General Condition, Paintwork
  • Doors / Frames / Fittings        → items named: Door, Door & Frame, Internal Door, Front Door, Skirting (if listed under doors)
  • Ceilings                         → items named: Ceiling, Coving
  • Lighting / Light Fittings        → items named: Lighting, Light Fitting, Light, Pendant, Spotlights
  • Walls                            → items named: Walls, Wall, Wall Surfaces
  • Windows / Fittings               → items named: Window, Window & Frame, Blind, Curtain, Curtain Track
  • Electrics / Heating              → items named: Sockets, Switches, Radiator, Boiler, Consumer Unit, Thermostat, Towel Rail
  • Woodwork / Flooring              → items named: Flooring, Floor, Carpet, Skirting Board, Architrave, Threshold, Laminate, Hard Floor
  • Contents / Furniture             → items named: Furniture, Contents, Wardrobe, Chest of Drawers, Sofa, Table, Bed,
                                        Built-in Storage, Built-in Wardrobe, Cupboard, Cabinet, Shelving, Storage
  • Appliances                       → items named: Oven, Hob, Fridge, Freezer, Washing Machine, Dishwasher, Extractor, Microwave
  • Sanitaryware / Bathrooms         → items named: Bath, Shower, Sink, Toilet, WC, Cistern, Taps, Mixer, Basin
  • Outdoor / Garden / External      → items named: Garden, Patio, Fence, Garage, Path, Driveway, Decking, Balcony

  CRITICAL — ITEM LOCK:
  An inspection item's ENTIRE condition and description stays together in ONE section.
  Do NOT read keywords inside an item's text and redistribute them to other sections.
  Example: a "Built-in Storage" item with condition "shelving worn, flooring to base damaged,
  socket inside not working" → the whole entry goes to Contents/Furniture.
  Do NOT extract "flooring" to Woodwork/Flooring or "socket" to Electrics/Heating.
  The item name, not the content text, determines the section.

════════════════════════════════════════════════════
PHASE 2 — INSPECTION FINDINGS
Draw from the following room-by-room inspection data to populate each section above.
Match each item to a section using its ITEM NAME (left of the colon), not keywords in its text.
════════════════════════════════════════════════════

{inspection_text}

════════════════════════════════════════════════════
ASSIGNMENT AND FORMATTING RULES
════════════════════════════════════════════════════

1. ONE FINDING PER LINE
   Each distinct defect or observation is a single line. Never write prose paragraphs or
   multi-sentence blocks. Never join separate issues with commas or "and".

2. ONE SECTION PER ITEM
   Each inspection item goes to exactly ONE summary section, chosen by item name.
   Do NOT repeat the same item in multiple sections.

3. GROUP BY ROOM
   Write the room name alone on its own line as a header. List each finding for that
   room on the line(s) immediately below it. Separate each room group from the next
   with ONE blank line (two newlines: \\n\\n). Do NOT run room groups together with
   only a single newline. Example of correct structure:
     Kitchen\\nCrack to plaster above window\\n\\nBedroom 1\\nHole to wall left of window
   Example of WRONG structure (no blank line between rooms):
     Kitchen\\nCrack to plaster above window\\nBedroom 1\\nHole to wall left of window

{severity_rule}

5. OVERVIEW RULE
   If a section is named "Overview" or "Property Description" (or similar), write exactly
   one sentence using PROPERTY DETAILS above. No findings, no defects, no other content.
   Format: "{overview_prefix}{property_description}"
   Append outdoor features if present in the data (e.g. "with garden", "with garage").

6. LIGHTING RULE
   If a section is named "Lighting" or "Light Fittings", the first line must always be
   exactly: "All tested for power"
   Then list non-functional fittings or rooms with blown/missing bulbs only.

7. APPLIANCES RULE
   If a section is named "Appliances", the first line must always be exactly:
   "All tested for power"
   Then list appliances with no power, non-functional, or major physical damage only.

8. EMPTY SECTIONS
   If no qualifying findings exist for a section, return an empty string "".
   Exception — Lighting and Appliances: return "All tested for power" (no additional text).
   Exception — Overview: return the one-sentence property summary only.
   NEVER write "In good order", "In fair order", "None noted", "No issues found", or "No defects noted".

9. NO ROOM OR ITEM SUFFIXES
   Never append "in [room]", "in the [room]", "to [item] in [room]", or any location
   reference that repeats the room header. The room header already establishes the
   location — adding it again is redundant.
   WRONG: "Crack to wall in Kitchen"  →  RIGHT: "Crack to wall"
   WRONG: "Mould to corner in Bedroom 1"  →  RIGHT: "Mould to corner"
   WRONG: "Worn carpet in Reception"  →  RIGHT: "Worn carpet"

10. FORMAT
   - Capitalise the first word of each line.
   - No bullet points, dashes, or numbering on observation lines.
   - UK English: "discolouration", "colour", "grey", "mould", "centre".

════════════════════════════════════════════════════
EXAMPLE OUTPUT (Walls section with findings in two rooms)
════════════════════════════════════════════════════
Kitchen
Crack to plaster above window
Mould to corner behind boiler

Bedroom 1
Large scuff marks to wall behind door
Hole to wall, left of window

Return ONLY valid JSON — no markdown, no extra text:
{{
  "<itemId>": {{"condition": "..."}}
}}

CRITICAL JSON FORMATTING:
- Use \\n between individual finding lines within a room group.
- Use \\n\\n (a blank line) between each room group — this is mandatory.
- Never use \\n\\n within a room group, only between them.
- Sections with no defects: {{"condition": ""}} (or "All tested for power" for Lighting/Appliances).
- Do NOT append room names to findings — the room header already shows the location."""

    message = client.messages.create(
        model='claude-haiku-4-5',
        max_tokens=4000,
        messages=[
            {'role': 'user',      'content': prompt},
            {'role': 'assistant', 'content': '{'},   # prefill forces JSON-only output
        ]
    )

    # Restore the prefilled '{' that was stripped from the response
    raw = ('{' + message.content[0].text).strip()
    raw = raw.replace('```json', '').replace('```', '').strip()

    stop_reason = getattr(message, 'stop_reason', None)
    if stop_reason == 'max_tokens':
        print(f'[condition-summary] output truncated (max_tokens reached) — raw[:400]: {raw[:400]}')

    try:
        filled = json.loads(_sanitise_json(raw))
    except json.JSONDecodeError:
        print(f'[condition-summary] JSON parse error (stop_reason={stop_reason}): {raw[:400]}')
        return jsonify({'error': 'AI returned an invalid response — please try again'}), 500

    # Log usage
    try:
        usage_log = TranscriptionUsage(
            call_type     = 'item',
            inspection_id = inspection_id,
            user_id       = int(get_jwt_identity()),
            audio_seconds = 0,
            input_tokens  = message.usage.input_tokens  if message.usage else 0,
            output_tokens = message.usage.output_tokens if message.usage else 0,
            section_type  = 'condition_summary',
        )
        db.session.add(usage_log)
        db.session.commit()
    except Exception:
        pass

    return jsonify({'filled': filled})


@transcribe_bp.route('/full', methods=['POST'])
@jwt_required()
def transcribe_full():
    """
    Full inspection continuous recording — legacy endpoint, kept for backward compatibility.

    Request JSON:
    {
      "audio":    "<base64-encoded audio>",
      "mimeType": "audio/webm",
      "template": { ...simplified template structure... }
    }

    Response JSON:
    {
      "transcript": "...",
      "filled": {
        "<sectionId>": {
          "<rowId>": { "description": "...", "condition": "..." }
        }
      }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    audio_b64 = data.get('audio')
    mime_type = data.get('mimeType', 'audio/webm')
  